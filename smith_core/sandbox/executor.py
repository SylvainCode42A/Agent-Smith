"""Secure sandbox executing LLM-generated code."""
import multiprocessing as mp
import sys
import time
from typing import Any, Optional

from smith_core.models import ExecResult, SandboxConfig
from smith_core.sandbox.mcp_client import McpClient
from smith_core.sandbox.manual import build_manual
from smith_core.sandbox.security import (build_safe_builtins,
                                        check_ast,
                                        make_audit_hook)

MAX_OUTPUT_CHARS = 10_000


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


def _limit_memory(max_memory_mb: int) -> None:
    """Cap the child's address space (enforced on Linux, ignored on macOS)."""
    try:
        import resource
        limit = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass

def _worker(conn, tool_specs: dict[str, list[str]],
            authorized_imports: list[str],
            allowed_dirs: list[str],
            max_memory_mb: int) -> None:
    """Body of the child process: wait for code, run it, report back."""
    _limit_memory(max_memory_mb)
    sys.stdout = _PipeStdout(conn)
    safe_builtins = build_safe_builtins(authorized_imports, allowed_dirs)
    namespace = {"__builtins__": safe_builtins,
                "__name__": "__main__",
                "final_answer": _final_answer}
    for name, params in tool_specs.items():
        namespace[name] = _make_tool_wrapper(conn, name, params)

    sys.addaudithook(make_audit_hook(allowed_dirs))

    while True:
        msg = conn.recv()

        if msg["type"] == "stop":
            break

        try:
            check_ast(msg["code"])
            exec(msg["code"], namespace)
            conn.send({"type": "done", "final": None, "error": None})

        except FinalAnswer as answer:
            conn.send({"type": "done", "final": str(answer.value),
                        "error": None})

        except (SystemExit, KeyboardInterrupt) as error:
            conn.send({"type": "done", "final": None, "error": None,
                        "control": type(error).__name__})

        except MemoryError:
            conn.send({"type": "done", "final": None,
                        "error": f"MemoryError: exceeded the "
                                f"{max_memory_mb} MB memory limit"})

        except Exception as error:
            conn.send({"type": "done", "final": None,
                        "error": f"{type(error).__name__}: {error}"})

def _truncate(text: str) -> tuple[str, list[str]]:
    """Keep the head and tail of a too long output, with a notice."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, []
    omitted = len(text) - MAX_OUTPUT_CHARS
    half = MAX_OUTPUT_CHARS // 2
    head = text[:half]
    tail = text[-half:] 
    marker = f"\n[... output truncated: {omitted} chars omitted ...]\n"
    return (head + marker + tail,
            [f"Output was truncated to {MAX_OUTPUT_CHARS} characters "
                f"({omitted} omitted)."])

class Sandbox:
    """Runs code in a child process with the configured restrictions."""

    def __init__(self, config: SandboxConfig,
                mcp: Optional[McpClient]) -> None:
        self._config = config
        self._mcp = mcp
        self._conn = None
        self._proc = None
        self._tool_specs: dict[str, list[str]] = {}

    def start(self) -> None:
        """Connect the MCP client once, then start the child."""
        if self._mcp is not None:
            self._mcp.connect()
            for tool in self._mcp.tools:
                properties = tool.inputSchema.get("properties", {})
                self._tool_specs[tool.name] = list(properties)
        self._spawn()

    def _spawn(self) -> None:
        """Start a fresh child process (also used to restart it)."""
        ctx = mp.get_context("spawn")
        self._conn, child_conn = ctx.Pipe()
        self._proc = ctx.Process(target=_worker,
                                args=(child_conn,
                                    self._tool_specs,
                                    self._config.authorized_imports,
                                    self._config.allowed_directories,
                                    self._config.max_memory_mb),
                                daemon=True)
        self._proc.start()

    def _restart(self) -> None:
        """Kill the child if needed and start a fresh one."""
        if self._proc.is_alive():
            self._proc.kill()
        self._proc.join()
        self._conn.close()
        self._spawn()

    def execute(self, code: str) -> ExecResult:
        """Run code in the persistent namespace."""
        chunks = []
        try:
            self._conn.send({"type": "exec", "code": code})
        except (BrokenPipeError, OSError):
            return self._on_crash(chunks)
        deadline = time.monotonic() + self._config.max_execution_time_seconds

        while True:
            remaining = deadline - time.monotonic()
            try:
                if not self._conn.poll(max(remaining, 0)):
                    return self._on_timeout(chunks)
                msg = self._conn.recv()
            except (EOFError, OSError):
                return self._on_crash(chunks)

            if msg["type"] == "stdout":
                chunks.append(msg["data"])

            elif msg["type"] == "tool":
                started = time.monotonic()
                self._conn.send(self._run_tool(msg["name"], msg["kwargs"]))
                deadline += time.monotonic() - started

            elif msg["type"] == "done":
                control = msg.get("control")
                if control == "KeyboardInterrupt":
                    raise KeyboardInterrupt
                if control == "SystemExit":
                    raise SystemExit("SystemExit raised by sandboxed code")
                output = "".join(chunks)
                if msg["error"] is not None:
                    if output and not output.endswith("\n"):
                        output += "\n"
                    output += f"ERROR: {msg['error']}"

                output, notices = _truncate(output)
                return ExecResult(output=output,
                                final_answer=msg["final"],
                                notices=notices)

    def _on_timeout(self, chunks: list[str]) -> ExecResult:
        """Kill the stuck child, start a fresh one, return partial output."""
        limit = self._config.max_execution_time_seconds
        self._restart()
        output, notices = _truncate("".join(chunks))
        return ExecResult(
            output=output,
            timed_out=True,
            notices=notices + [
                f"Execution exceeded {limit}s and was stopped. "
                "Output above is partial.",
                "The sandbox was restarted: all variables were reset.",
            ])

    def _on_crash(self, chunks: list[str]) -> ExecResult:
        """The child died by itself: restart it and tell the LLM."""
        self._proc.join(timeout=1)
        code = self._proc.exitcode
        self._restart()
        return ExecResult(
            output="".join(chunks),
            notices=[f"The sandbox process crashed (exit code {code}).",
                    "The sandbox was restarted: all variables were reset."])

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
        tools = self._mcp.tools if self._mcp is not None else []
        return build_manual(tools, self._config)

    def close(self) -> None:
        """Kill the child process and close the MCP client."""
        if self._proc is not None:
            try:
                self._conn.send({"type": "stop"})
            except (BrokenPipeError, OSError):
                pass
            self._proc.join(timeout=3)
            if self._proc.is_alive():
                self._proc.kill()
            self._proc = None
        if self._mcp is not None:
            self._mcp.close()
