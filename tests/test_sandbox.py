import pytest
import os
import sys
import time
import subprocess

from smith_core.models import SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.security import is_import_allowed
from smith_core.sandbox.mcp_client import McpClient


@pytest.fixture(scope="module")
def sandbox():
    sb = Sandbox(SandboxConfig(), None)
    sb.start()
    yield sb          # tous les tests du fichier utilisent cette sandbox
    sb.close()        # exécuté à la fin, même si un test échoue


# ---------- règle seule (aucun process) ----------
ALLOWED = ["math", "math.*", "collections.*", "re"]

@pytest.mark.parametrize("name, expected", [
    ("math", True),
    ("collections.abc", True),
    ("mathx", False),
    ("os", False),
    ("re.sub", False),
])
def test_is_import_allowed(name, expected):
    assert is_import_allowed(name, ALLOWED) is expected


# ---------- dans la sandbox ----------
@pytest.mark.parametrize("code", [
    "import math",
    "from collections import abc",
    "import collections.abc",
    "import random"
])
def test_import_allowed(sandbox, code):
    assert "ERROR" not in sandbox.execute(code).output


@pytest.mark.parametrize("code", [
    "import os",
    "__import__('subprocess')",
    "from os import path",
    "import os.path",
    "from . import x"
])
def test_import_blocked(sandbox, code):
    assert "ImportError" in sandbox.execute(code).output

def test_fromlist_submodule_blocked():
    config = SandboxConfig(authorized_imports=["collections"])
    sb = Sandbox(config, None)
    sb.start()
    try:
        out = sb.execute("from collections import abc").output
        assert "collections.abc" in out and "ImportError" in out
    finally:
        sb.close()

# ---------- restricted builtins ----------
@pytest.mark.parametrize("code", [
    "eval(\"__import__('os')\")",
    "eval('1 + 1')",
    "exec('x = 1')",
    "compile('1', 'f', 'eval')",
    "globals()",
    "vars()",
])
def test_builtin_blocked(sandbox, code):
    assert "NameError" in sandbox.execute(code).output


# ---------- dunders ----------
@pytest.mark.parametrize("code", [
    "().__class__",
    "().__class__.__base__.__subclasses__()",
    "__builtins__",
    "def f(): return f.__globals__",
])
def test_dunder_blocked_by_ast(sandbox, code):
    assert "SecurityError" in sandbox.execute(code).output


@pytest.mark.parametrize("code", [
    "getattr((), '__class__')",
    "getattr((), '__cl' + 'ass__')",
])
def test_dunder_blocked_by_getattr(sandbox, code):
    assert "AttributeError" in sandbox.execute(code).output


# ---------- we did not block too much ----------
@pytest.mark.parametrize("code", [
    "if __name__ == '__main__': pass",
    "print(getattr('abc', 'upper')())",
    "print(getattr('abc', 'zzz', 0))",
    "class A:\n    def __init__(self):\n        self.v = 3\nprint(A().v)",
    "try:\n    int('x')\nexcept ValueError:\n    pass",
])
def test_safe_code_still_works(sandbox, code):
    assert "ERROR" not in sandbox.execute(code).output

# ---------- files ----------
@pytest.mark.parametrize("code", [
    "open('/etc/passwd')",
    "open('/tmp/agent/../../etc/passwd')",
    "open('/tmp/agent_evil/x', 'w')",
    "open(3)",
])
def test_open_blocked(sandbox, code):
    assert "PermissionError" in sandbox.execute(code).output


def test_open_allowed_dir(sandbox):
    os.makedirs("/tmp/agent", exist_ok=True)
    code = ("open('/tmp/agent/t.txt', 'w').write('ok')\n"
            "print(open('/tmp/agent/t.txt').read())")
    assert sandbox.execute(code).output == "ok\n"


# ---------- audit hook: even through allowed modules ----------
@pytest.mark.parametrize("code", [
    "import random; random._os.system('echo PIRATE')",
    "import typing; typing.sys.modules['os'].system('echo PIRATE')",
])
def test_hidden_os_blocked(sandbox, code):
    assert "PermissionError" in sandbox.execute(code).output


# ---------- audit hook: config that allows dangerous modules ----------
@pytest.fixture(scope="module")
def open_sandbox():
    imports = SandboxConfig().authorized_imports + ["os", "socket",
                                                    "subprocess"]
    sb = Sandbox(SandboxConfig(authorized_imports=imports), None)
    sb.start()
    yield sb
    sb.close()


@pytest.mark.parametrize("code", [
    "import os; os.system('ls')",
    "import os; os.open('/etc/passwd', 0)",
    "import subprocess; subprocess.run(['ls'])",
    "import socket; socket.create_connection(('1.1.1.1', 80), timeout=2)",
])
def test_hook_blocks_even_if_import_allowed(open_sandbox, code):
    assert "PermissionError" in open_sandbox.execute(code).output

# ---------- timeout ----------
def test_timeout_partial_output_and_restart():
    sb = Sandbox(SandboxConfig(max_execution_time_seconds=2), None)
    sb.start()
    try:
        sb.execute("x = 1")
        started = time.monotonic()
        res = sb.execute("print('a')\nwhile True: pass")
        assert time.monotonic() - started < 5
        assert res.timed_out is True
        assert res.output == "a\n"
        assert res.notices
        assert "NameError" in sb.execute("print(x)").output
        assert sb.execute("print(1 + 1)").output == "2\n"
    finally:
        sb.close()

def test_crash_is_reported_and_sandbox_restarts():
    sb = Sandbox(SandboxConfig(authorized_imports=["os"]), None)
    sb.start()
    try:
        sb.execute("x = 1")
        res = sb.execute("import os; os._exit(3)")
        assert any("crashed" in n for n in res.notices)
        assert "NameError" in sb.execute("print(x)").output
        assert sb.execute("print(2)").output == "2\n"
    finally:
        sb.close()

@pytest.mark.skipif(sys.platform == "darwin",
                    reason="RLIMIT_AS is not enforced on macOS")
def test_memory_limit():
    sb = Sandbox(SandboxConfig(max_memory_mb=256), None)
    sb.start()
    try:
        out = sb.execute("x = 'a' * (1024 ** 3)").output
        assert "MemoryError" in out
        assert sb.execute("print(2)").output == "2\n"
    finally:
        sb.close()

def test_output_is_truncated(sandbox):
    res = sandbox.execute("print('a' * 50_000)")
    assert len(res.output) < 11_000
    assert "output truncated" in res.output
    assert res.notices
    assert res.output.rstrip().endswith("a")

@pytest.mark.parametrize("code, exc", [
    ("raise SystemExit", SystemExit),
    ("raise KeyboardInterrupt", KeyboardInterrupt),
])
def test_control_exceptions_reach_caller(code, exc):
    sb = Sandbox(SandboxConfig(), None)
    sb.start()
    try:
        sb.execute("x = 1")
        with pytest.raises(exc):
            sb.execute(code)
        assert sb.execute("print(x)").output == "1\n"
    finally:
        sb.close()

PORT = 8765                                  # not 8000: avoid clashes


@pytest.fixture(scope="module")
def http_server():
    proc = subprocess.Popen(
        [sys.executable, "mcp_tools_mbpp.py", "--http", "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)                            # give the server time to start
    yield f"http://127.0.0.1:{PORT}/mcp"
    proc.terminate()
    proc.wait(timeout=5)


def test_http_connect_and_call(http_server):
    client = McpClient.from_http(http_server)
    client.connect()
    try:
        assert [t.name for t in client.tools] == ["run_tests"]
        out = client.call_tool("run_tests", {"code": "def f(): return 1",
                                            "test_list": ["assert f()==1"]})
        assert '"success": true' in out
    finally:
        client.close()


def test_http_bad_url_fails_cleanly():
    client = McpClient.from_http("http://127.0.0.1:9/mcp")
    with pytest.raises(RuntimeError):
        client.connect(timeout=10)