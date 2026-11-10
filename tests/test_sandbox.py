import pytest

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
    "eval(\"__import__('os')\")",
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
