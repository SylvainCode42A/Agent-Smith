"""`uv run sandbox`: an interactive REPL running code inside the sandbox."""
import argparse
import sys
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from smith_core.models import SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.mcp_client import McpClient


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Read the command line options."""
    parser = argparse.ArgumentParser(
        prog="sandbox",
        description="Interactive sandbox REPL (type 'exit' or Ctrl+D to quit).",
    )
    parser.add_argument("config", nargs="?",
                        help="path to a SandboxConfig JSON file")
    server = parser.add_mutually_exclusive_group()
    server.add_argument("--mcp-stdio", metavar="COMMAND",
                        help='MCP server command, e.g. "python mcp_tools_mbpp.py"')
    server.add_argument("--mcp-server", metavar="URL",
                        help="MCP server URL (streamable HTTP)")
    return parser.parse_args(argv)


def load_config(path: Optional[str]) -> SandboxConfig:
    """Load the JSON config, or use the defaults when no path is given."""
    if path is None:
        return SandboxConfig()
    try:
        return SandboxConfig.model_validate_json(Path(path).read_text())
    except OSError as error:
        raise SystemExit(f"Cannot read config file: {error}")
    except ValidationError as error:
        raise SystemExit(f"Invalid config file {path}:\n{error}")


def read_entry() -> Optional[str]:
    """Read one entry; None means 'quit' (exit or Ctrl+D)."""
    try:
        line = input(">>> ")
    except EOFError:
        print()
        return None
    if line.strip() == "exit":
        return None

    lines = [line]
    if line.rstrip().endswith(":"):
        while True:
            try:
                next_line = input("... ")
            except EOFError:
                break
            if next_line.strip() == "":
                break
            lines.append(next_line)
    return "\n".join(lines)


def repl(sandbox: Sandbox) -> None:
    """Read -> execute -> print, until the user quits."""
    while True:
        try:
            code = read_entry()
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            continue
        if code is None:
            break
        if not code.strip():
            continue

        result = sandbox.execute(code)
        if result.output:
            print(result.output.rstrip("\n"))
        for notice in result.notices:
            print(f"[NOTICE] {notice}")        
        if result.final_answer is not None:
            print(f"FINAL ANSWER: {result.final_answer}")


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point of `uv run sandbox`."""
    args = parse_args(argv)
    config = load_config(args.config)

    if args.mcp_server is not None:
        print("--mcp-server is not supported yet (HTTP comes in phase 2).",
            file=sys.stderr)
        return 1

    mcp = None
    if args.mcp_stdio is not None:
        mcp = McpClient.from_stdio(args.mcp_stdio)

    sandbox = Sandbox(config, mcp)
    try:
        sandbox.start()
    except RuntimeError as error:
        print(f"Sandbox failed to start: {error}", file=sys.stderr)
        sandbox.close()
        return 1

    try:
        if mcp is not None:
            names = ", ".join(tool.name for tool in mcp.tools)
            print(f"MCP tools: {names}")
        repl(sandbox)
    finally:
        sandbox.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())