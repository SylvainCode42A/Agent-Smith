"""Independent tests of the SWE-bench MCP tools, in local mode.

A small git repository is created in a temporary folder, and
TESTBED_PATH points to it, exactly like the moulinette does.
"""
import importlib
import subprocess

import pytest


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A fresh git repo + the tools module configured to use it."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "math.py").write_text(
        "def add(a, b):\n"
        "    return a - b\n"
        "\n"
        "def address():\n"
        "    return 'Nice'\n")
    (repo / "app.py").write_text(
        "from pkg.math import add\n"
        "\n"
        "total = add(1, 2)\n")
    (repo / "eval.sh").write_text(
        "echo 'running tests'\n"
        "echo '1 failed, 3 passed'\n"
        "exit 1\n")
    for command in (["git", "init", "-q"],
                    ["git", "add", "-A"],
                    ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "init"]):
        subprocess.run(command, cwd=repo, check=True)

    monkeypatch.setenv("TESTBED_PATH", str(repo))
    monkeypatch.setenv("EVAL_SCRIPT_PATH", str(repo / "eval.sh"))
    monkeypatch.delenv("SWEBENCH_CONTAINER", raising=False)
    import mcp_tools_swebench
    module = importlib.reload(mcp_tools_swebench)   # re-read the variables
    module.REPO = str(repo)
    return module


# ---------- run_command ----------
def test_run_command_ok(tools):
    out = tools.run_command("ls")
    assert "exit_code: 0" in out and "app.py" in out


def test_run_command_error(tools):
    out = tools.run_command("cat absent.py")
    assert "exit_code: 1" in out and "No such file" in out


# ---------- get_patch ----------
def test_get_patch_empty_then_diff(tools):
    assert tools.get_patch() == ""
    tools.edit_file("pkg/math.py", "return a - b", "return a + b")
    patch = tools.get_patch()
    assert "-    return a - b" in patch and "+    return a + b" in patch


# ---------- list_files ----------
def test_list_files(tools):
    out = tools.list_files(".", "*.py")
    assert out.splitlines() == [f"{tools.REPO}/app.py",
                                f"{tools.REPO}/pkg/math.py"]
    assert tools.list_files(".", "*.txt") == "No files found."


# ---------- read_file ----------
def test_read_file_format(tools):
    assert tools.read_file("pkg/math.py", 1, 2) == (
        "1: def add(a, b):\n2:     return a - b")


def test_read_file_errors(tools):
    assert "out of range (file has 5 lines)" in tools.read_file(
        "pkg/math.py", 99)
    assert tools.read_file("absent.py").startswith("Error")


# ---------- search_code ----------
def test_search_code_format(tools):
    out = tools.search_code("total = ")
    assert out == f"{tools.REPO}/app.py:3 total = add(1, 2)"
    assert tools.search_code("introuvable") == "No matches found."


# ---------- search_function_or_class_definition_in_code ----------
def test_search_definition(tools):
    out = tools.search_function_or_class_definition_in_code("add")
    assert out == f"{tools.REPO}/pkg/math.py:1 def add(a, b):"   # not address
    assert tools.search_function_or_class_definition_in_code(
        "a|b").startswith("Error")


# ---------- find_references ----------
def test_find_references(tools):
    out = tools.find_references("add", "pkg/math.py", 1)
    assert f"{tools.REPO}/app.py:3 total = add(1, 2)" in out
    assert "address" not in out
    assert tools.find_references("add", "pkg/math.py", 2).startswith("Error")


# ---------- edit_file ----------
def test_edit_file_ok(tools):
    out = tools.edit_file("pkg/math.py", "return a - b", "return a + b")
    assert out == "Edited pkg/math.py at line 2."
    assert "return a + b" in tools.read_file("pkg/math.py")


def test_edit_file_guards(tools):
    assert "not found" in tools.edit_file("pkg/math.py", "zzz", "x")
    assert "found 2 times" in tools.edit_file("pkg/math.py", "return", "x")
    out = tools.edit_file("pkg/math.py", "return a - b", "return a +")
    assert "syntax" in out and "NOT modified" in out
    assert "return a - b" in tools.read_file("pkg/math.py")   # untouched


# ---------- run_tests ----------
def test_run_tests(tools):
    out = tools.run_tests()
    assert "exit_code: 1" in out and "1 failed, 3 passed" in out


def test_run_tests_missing_script(tools, monkeypatch):
    monkeypatch.setattr(tools, "EVAL_SCRIPT", "/nope/eval.sh")
    assert tools.run_tests().startswith("Error: no eval script")
