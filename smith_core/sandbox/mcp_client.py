"""Synchronous MCP client (stdio) used by the sandbox."""
import asyncio
import os
import shlex
import threading
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpClient:
    """Keeps one MCP session open in a background asyncio thread."""

    def __init__(self, params: StdioServerParameters) -> None:
        self._params = params
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: Exception | None = None
        self.tools: list = []

    @classmethod
    def from_stdio(cls, command: str) -> "McpClient":
        """Build a client from a shell command, e.g. 'python mcp_tools_mbpp.py'."""
        parts = shlex.split(command)
        params = StdioServerParameters(
            command=parts[0],
            args=parts[1:],
            env=dict(os.environ),
        )
        return cls(params)

    def connect(self, timeout: float = 30) -> None:
        """Start the background thread and wait until the session is ready."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_until_complete,
            args=(self._run_forever(),),
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError(f"MCP server not ready after {timeout}s")
        if self._error is not None:
            raise RuntimeError(f"MCP connection failed: {self._error}")

    async def _run_forever(self) -> None:
        """Runs inside the thread: open the session, then wait for close()."""
        self._stop = asyncio.Event()
        try:
            async with stdio_client(self._params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self.tools = (await session.list_tools()).tools
                    self._ready.set()
                    await self._stop.wait()
        except Exception as error:
            self._error = error
            self._ready.set()

    def call_tool(self, name: str, arguments: dict[str, Any],
                timeout: float = 600) -> str:
        """Call a tool synchronously and return its text output."""
        if self._session is None or self._loop is None:
            raise RuntimeError("McpClient is not connected")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments), self._loop)
        result = future.result(timeout)
        text = "\n".join(c.text for c in result.content if c.type == "text")
        if result.isError:
            raise RuntimeError(text)
        return text

    def close(self) -> None:
        """Ask the background loop to stop and wait for the thread."""
        if self._loop is None or self._stop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)
        self._session = None