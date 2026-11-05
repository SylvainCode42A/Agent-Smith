"""Fake sandbox for development: same interface as Sandbox, NO security.

Runs LLM code with a plain exec() in the current process.
Never use it during evaluation.
"""
import io
import traceback
from contextlib import redirect_stdout
from typing import Any, Dict, Optional

from smith_core.models import ExecResult, SandboxConfig
from smith_core.sandbox.mcp_client import McpClient


class FakeSandbox:
    """Unsafe stand-in for Sandbox, used to test the agent loop."""

    def __init__(self, config: SandboxConfig,
                mcp: Optional[McpClient]) -> None:
        """Store the config; the MCP client is ignored for now."""
        self._ns: Dict[str, Any] = {}
        self._final: Optional[str] = None

    def start(self) -> None:
        """Create a fresh namespace with final_answer injected."""
        self._ns = {"final_answer": self._final_answer}
        self._final = None

    def execute(self, code: str) -> ExecResult:
        """Run code in the persistent namespace and return the result."""
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(code, self._ns)
        except Exception:
            buf.write(traceback.format_exc())
        return ExecResult(output=buf.getvalue(), final_answer=self._final)

    def manual(self) -> str:
        """Return the tool manual to put in the prompt."""
        return (
            "Available functions:\n"
            "- final_answer(answer: str) -> None: submit your solution "
            "and stop.\n"
        )

    def close(self) -> None:
        """Drop the namespace."""
        self._ns = {}

    def _final_answer(self, answer: Any) -> None:
        """Store the answer; the loop reads it from ExecResult."""
        self._final = str(answer)
