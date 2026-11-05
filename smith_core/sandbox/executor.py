"""Secure sandbox executing LLM-generated code. Signatures only for now."""
from typing import Optional

from smith_core.models import ExecResult, SandboxConfig
from smith_core.sandbox.mcp_client import McpClient


class Sandbox:
    """Runs code in a child process with the configured restrictions."""

    def __init__(self, config: SandboxConfig,
                mcp: Optional[McpClient]) -> None:
        ...

    def start(self) -> None:
        """Start the child process and connect the MCP client."""
        ...

    def execute(self, code: str) -> ExecResult:
        """Run code in the persistent namespace."""
        ...

    def manual(self) -> str:
        """Return the tool manual to put in the prompt."""
        ...

    def close(self) -> None:
        """Kill the child process and close the MCP client."""
        ...