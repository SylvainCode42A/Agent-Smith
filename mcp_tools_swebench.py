"""MCP server exposing the SWE-bench tools.

Run with:  TESTBED_PATH=/path/to/repo python mcp_tools_swebench.py          (stdio)
            TESTBED_PATH=/path/to/repo python mcp_tools_swebench.py --http   (HTTP)
"""
import os
import subprocess
import shlex

from mcp.server.fastmcp import FastMCP

# Repository root. The moulinette sets TESTBED_PATH when it tests the tools
# on their own; inside the SWE-bench image the repo lives in /testbed.
TESTBED = os.environ.get("TESTBED_PATH", "/testbed")
TIMEOUT_S = 120
MAX_OUTPUT_CHARS = 10_000
# Where the eval script is: /eval.sh is where the moulinette puts it.
EVAL_SCRIPT = os.environ.get("EVAL_SCRIPT_PATH", "/eval.sh")
TESTS_TIMEOUT_S = 600
# Name of the SWE-bench container. Empty: run locally (TESTBED_PATH).
CONTAINER = os.environ.get("SWEBENCH_CONTAINER", "")
CONDA = ". /opt/miniconda3/bin/activate testbed 2>/dev/null; "

mcp = FastMCP("swebench-tools")


def _truncate(text: str) -> str:
    """Cut a too long tool output and say so explicitly."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_OUTPUT_CHARS
    return (text[:MAX_OUTPUT_CHARS]
            + f"\n[output truncated: {omitted} chars omitted]")


def _abs(path: str) -> str:
    """Absolute path: relative paths are taken from the repository root."""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(TESTBED, path))


def _sh(command: str, workdir: str | None = None,
        timeout: int = TIMEOUT_S,
        stdin: str | None = None) -> tuple[int, str, str]:
    """Run a shell command in the repo (locally or inside the container)."""
    cwd = _abs(workdir) if workdir else TESTBED
    if CONTAINER:
        argv = ["docker", "exec", "-i", "-w", cwd, CONTAINER,
                "bash", "-c", command]
        local_cwd = None
    else:
        argv = ["bash", "-c", command]
        local_cwd = cwd
    try:
        proc = subprocess.run(argv, cwd=local_cwd, input=stdin,
                            capture_output=True, text=True,
                            timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s"
    except OSError as error:
        return 1, "", f"Cannot run command: {error}"
    return proc.returncode, proc.stdout, proc.stderr


def _read(path: str) -> str:
    """Whole content of a file of the repo."""
    if CONTAINER:
        code, out, err = _sh(f"cat {shlex.quote(_abs(path))}")
        if code != 0:
            raise OSError(err.strip())
        return out
    with open(_abs(path), encoding="utf-8", errors="replace") as file:
        return file.read()


def _write(path: str, text: str) -> None:
    """Replace the whole content of a file of the repo."""
    if CONTAINER:
        code, _, err = _sh(f"cat > {shlex.quote(_abs(path))}", stdin=text)
        if code != 0:
            raise OSError(err.strip())
        return
    with open(_abs(path), "w", encoding="utf-8") as file:
        file.write(text)


def _format_grep(out: str) -> str:
    """'path:12:content' lines from grep -n → 'path:12 content'."""
    results = []
    for line in out.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path, number, content = parts
        results.append(f"{path}:{number} {content}")
    return _truncate("\n".join(results))


def _truncate_tail(text: str) -> str:
    """Keep the END of a too long output (test summaries are at the end)."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_OUTPUT_CHARS
    return (f"[output truncated: first {omitted} chars omitted]\n"
            + text[-MAX_OUTPUT_CHARS:])


@mcp.tool()
def run_command(command: str, workdir: str = ".") -> str:
    """Execute a shell command in the given directory of the repository.

    Returns:
        The exit code, then stdout and stderr.
    """
    if CONTAINER:
        command = CONDA + command
    code, out, err = _sh(command, workdir)
    result = (f"exit_code: {code}\n"
                f"stdout:\n{out}\n"
                f"stderr:\n{err}")
    return _truncate(result)


@mcp.tool()
def get_patch() -> str:
    """Return the unified git diff of all changes made to the repository.

    Returns:
        The patch to submit with final_answer(get_patch()).
    """
    code, out, err = _sh("git -c core.fileMode=false diff")
    if code != 0:
        return f"Error: git diff failed: {err}"
    return out


@mcp.tool()
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """List files in a directory (recursively) whose name matches a pattern.

    Returns:
        One absolute path per line, sorted.
    """
    command = (f"find {shlex.quote(_abs(directory))} -type f "
                f"-name {shlex.quote(pattern)} -not -path '*/.git/*'")
    code, out, err = _sh(command)
    if code != 0:
        return f"Error: {err}"
    files = sorted(out.splitlines())
    if not files:
        return "No files found."
    return _truncate("\n".join(files))


@mcp.tool()
def read_file(filepath: str, start_line: int = 1,
                end_line: int | None = None) -> str:
    """Read a file with line numbers ('<n>: <text>'), from start_line to end_line.

    Returns:
        The selected lines, numbered from 1.
    """
    try:
        lines = _read(filepath).splitlines()
    except OSError as error:
        return f"Error: cannot read {filepath}: {error}"

    if not lines:
        return "(empty file)"

    if end_line is None:
        end_line = len(lines)

    if start_line < 1 or start_line > len(lines):
        return (f"Error: start_line out of range "
                f"(file has {len(lines)} lines)")

    if end_line < start_line:
        return "Error: end_line must be >= start_line"

    numbered = []
    for n in range(start_line, min(end_line, len(lines)) + 1):
        numbered.append(f"{n}: {lines[n - 1]}")
    return _truncate("\n".join(numbered))


@mcp.tool()
def search_code(pattern: str, file_pattern: str = "*.py",
                path: str = ".") -> str:
    """Search a regex in all files whose NAME matches file_pattern
    (a glob like '*.py', not a directory), inside the directory path.

    Returns:
        One match per line: '/absolute/path:<line> <content>'.
    """
    command = (f"grep -rnIE --exclude-dir=.git "
                f"--include={shlex.quote(file_pattern)} "
                f"-e {shlex.quote(pattern)} {shlex.quote(_abs(path))}")
    code, out, err = _sh(command)
    if code == 1:
        return "No matches found."
    if code != 0:
        return f"Error: {err}"

    return _format_grep(out)


@mcp.tool()
def search_function_or_class_definition_in_code(name: str) -> str:
    """Find where a function or a class is defined (def / class lines).

    Returns:
        Same format as search_code: '/absolute/path:<line> <content>'.
    """
    if not name.isidentifier():
        return f"Error: '{name}' is not a valid Python name"
    pattern = (r"^[[:space:]]*(async[[:space:]]+)?(def|class)[[:space:]]+"
                + name + r"([^[:alnum:]_]|$)")
    return search_code(pattern)


@mcp.tool()
def find_references(name: str, filepath: str, line: int) -> str:
    """Find all usages of the symbol `name` defined/used at filepath:line.

    Returns:
        Same format as search_code: '/absolute/path:<line> <content>'.
    """
    if not name.isidentifier():
        return f"Error: '{name}' is not a valid Python name"

    # 1. check that the symbol is really at filepath:line
    try:
        lines = _read(filepath).splitlines()
    except OSError as error:
        return f"Error: cannot read {filepath}: {error}"

    if line < 1 or line > len(lines) or name not in lines[line - 1]:
        return f"Error: '{name}' not found at {filepath}:{line}"

    # 2. search every whole-word occurrence in the repository
    command = (f"grep -rnIwF --exclude-dir=.git --include='*.py' "
                f"-e {shlex.quote(name)} {shlex.quote(TESTBED)}")
    code, out, err = _sh(command)
    if code == 1:
        return "No references found."
    if code != 0:
        return f"Error: {err}"
    return _format_grep(out)


@mcp.tool()
def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace one exact occurrence of old_str by new_str in a file.

    old_str must appear exactly once (add surrounding lines if needed).
    Python files are syntax-checked: a broken edit is refused.

    Returns:
        A confirmation with the line number, or an error.
    """
    if not old_str:
        return "Error: old_str must not be empty"
    try:
        content = _read(filepath)
    except OSError as error:
        return f"Error: cannot read {filepath}: {error}"

    count = content.count(old_str)

    if count == 0:
        return f"Error: old_str not found in {filepath}"
    if count > 1:
        return (f"Error: old_str found {count} times in "
                f"{filepath}, add more surrounding lines")

    new_content = content.replace(old_str, new_str, 1)

    if filepath.endswith(".py"):
        try:
            compile(new_content, filepath, "exec")
        except SyntaxError as error:
            return (f"Error: this edit would break the Python syntax "
                    f"(line {error.lineno}: {error.msg}). "
                    f"{filepath} was NOT modified.")

    _write(filepath, new_content)
    line = content[:content.index(old_str)].count("\n") + 1
    return f"Edited {filepath} at line {line}."


@mcp.tool()
def run_tests() -> str:
    """Run the task's evaluation script (the official tests).

    Returns:
        The exit code (0 = tests passed), then the end of the test output.
    """
    code, _, _ = _sh(f"test -f {shlex.quote(EVAL_SCRIPT)}")
    if code != 0:
        return f"Error: no eval script found at {EVAL_SCRIPT}"

    code, out, err = _sh(f"bash {shlex.quote(EVAL_SCRIPT)}",
                        timeout=TESTS_TIMEOUT_S)
    result = (f"exit_code: {code}\n"
                f"stdout:\n{out}\n"
                f"stderr:\n{err}")
    return _truncate_tail(result)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SWE-bench MCP server")
    parser.add_argument("--http", action="store_true",
                        help="serve over streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
