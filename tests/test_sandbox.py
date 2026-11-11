import pytest
import os

from smith_core.models import SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.security import is_import_allowed


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
