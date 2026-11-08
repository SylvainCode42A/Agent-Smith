"""Secure sandbox executing LLM-generated code."""
import multiprocessing as mp
import sys
from typing import Any, Optional

from smith_core.models import ExecResult, SandboxConfig
from smith_core.sandbox.mcp_client import McpClient


class FinalAnswer(BaseException):
    """Raised by final_answer() to stop the code and carry the answer."""

    def __init__(self, value: Any) -> None:
        super().__init__(value)
        self.value = value


class _PipeStdout:
    """Replaces sys.stdout in the child: each write is sent to the parent."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def write(self, text: str) -> int:
        if text:
            self._conn.send({"type": "stdout", "data": text})
        return len(text)

    def flush(self) -> None:
        pass


def _final_answer(value: Any) -> None:
    """Injected in the namespace: ends the task with this answer."""
    raise FinalAnswer(value)


def _make_tool_wrapper(conn, name: str, params: list[str]):
    """Build a Python function that asks the parent to call an MCP tool."""
    def tool(*args, **kwargs):
        for param, value in zip(params, args):
            kwargs[param] = value
        conn.send({"type": "tool", "name": name, "kwargs": kwargs})
        reply = conn.recv()
        if not reply["ok"]:
            raise RuntimeError(reply["value"])
        return reply["value"]
    tool.__name__ = name
    return tool


def _worker(conn, tool_specs: dict[str, list[str]]) -> None:
    """Body of the child process: wait for code, run it, report back."""
    sys.stdout = _PipeStdout(conn)
    namespace = {"final_answer": _final_answer}
    for name, params in tool_specs.items():
        namespace[name] = _make_tool_wrapper(conn, name, params)

    while True:
        msg = conn.recv()

        if msg["type"] == "stop":
            break

        try:
            exec(msg["code"], namespace)
            conn.send({"type": "done", "final": None, "error": None})

        except FinalAnswer as answer:
            conn.send({"type": "done", "final": str(answer.value),
                    "error": None})

        except Exception as error:
            conn.send({"type": "done", "final": None,
                    "error": f"{type(error).__name__}: {error}"})


class Sandbox:
    """Runs code in a child process with the configured restrictions."""

    def __init__(self, config: SandboxConfig,
                mcp: Optional[McpClient]) -> None:
        self._config = config
        self._mcp = mcp
        self._conn = None
        self._proc = None

    def start(self) -> None:
        """Start the child process and connect the MCP client."""
        tool_specs = {}
        if self._mcp is not None:
            self._mcp.connect()
            for tool in self._mcp.tools:
                properties = tool.inputSchema.get("properties", {})
                tool_specs[tool.name] = list(properties)

        ctx = mp.get_context("spawn")
        self._conn, child_conn = ctx.Pipe()
        self._proc = ctx.Process(target=_worker,
                                args=(child_conn, tool_specs),
                                daemon=True)
        self._proc.start()

    def execute(self, code: str) -> ExecResult:
        """Run code in the persistent namespace."""
        self._conn.send({"type": "exec", "code": code})
        chunks = []
        while True:
            msg = self._conn.recv()

            if msg["type"] == "stdout":
                chunks.append(msg["data"])

            elif msg["type"] == "tool":
                self._conn.send(self._run_tool(msg["name"], msg["kwargs"]))

            elif msg["type"] == "done":
                output = "".join(chunks)
                if msg["error"] is not None:
                    if output and not output.endswith("\n"):
                        output += "\n"
                    output += f"ERROR: {msg['error']}"
                return ExecResult(output=output,
                                final_answer=msg["final"])

    def _run_tool(self, name: str, kwargs: dict) -> dict:
        """Call the MCP tool for the child and build the reply message."""
        if self._mcp is None:
            return {"type": "tool_result", "ok": False,
                    "value": "No MCP server connected"}
        try:
            value = self._mcp.call_tool(name, kwargs)
            return {"type": "tool_result", "ok": True, "value": value}
        except Exception as error:
            return {"type": "tool_result", "ok": False, "value": str(error)}

    def manual(self) -> str:
        """Return the tool manual to put in the prompt."""
        ...

    def close(self) -> None:
        """Kill the child process and close the MCP client."""
        if self._proc is not None:
            self._conn.send({"type": "stop"})
            self._proc.join(timeout=3)
            if self._proc.is_alive():
                self._proc.kill()
            self._proc = None
        if self._mcp is not None:
            self._mcp.close()
