"""MCP server exposing the MBPP tools.

Run with:  python mcp_tools_mbpp.py   (stdio transport)
"""
import json
import subprocess
import sys
import tempfile

from mcp.server.fastmcp import FastMCP

TIMEOUT_S = 10
MAX_OUTPUT_CHARS = 4000

mcp = FastMCP("mbpp-tools")

# Script executed by the child process.
# It reads {"code": ..., "tests": [...]} as JSON on stdin.
RUNNER = r'''
import json
import sys

payload = json.loads(sys.stdin.read())
namespace = {}

try:
    exec(payload["code"], namespace)
except BaseException as error:
    print(f"ERROR in solution: {type(error).__name__}: {error}")
    sys.exit(1)

failed = 0
for test in payload["tests"]:
    try:
        exec(test, namespace)
        print(f"PASS: {test}")
    except AssertionError:
        failed += 1
        print(f"FAIL: {test}")
    except BaseException as error:
        failed += 1
        print(f"FAIL: {test} -> {type(error).__name__}: {error}")

sys.exit(0 if failed == 0 else 1)
'''


def _truncate(text: str) -> str:
    """Cut text to MAX_OUTPUT_CHARS and say so explicitly."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_OUTPUT_CHARS
    return (text[:MAX_OUTPUT_CHARS]
            + f"\n[output truncated: {omitted} chars omitted]")


@mcp.tool()
def run_tests(code: str, test_list: list[str]) -> str:
    """Run a candidate solution against assert statements.

    Args:
        code: Python source defining the solution (e.g. a function).
        test_list: assert statements, e.g. ["assert add(1, 2) == 3"].

    Returns:
        A JSON string {"success": bool, "output": str}. "output" has one
        PASS/FAIL line per assert.
    """
    payload = json.dumps({"code": code, "tests": test_list})
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", RUNNER],
                input=payload,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                cwd=tmp_dir,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"success": False,
                            "output": f"Timeout after {TIMEOUT_S}s"})
    output = _truncate(proc.stdout + proc.stderr)
    return json.dumps({"success": proc.returncode == 0, "output": output})


if __name__ == "__main__":
    mcp.run()