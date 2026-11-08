from smith_core.models import SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.mcp_client import McpClient


def make_sandbox():
    mcp = McpClient.from_stdio("python mcp_tools_mbpp.py")
    sandbox = Sandbox(SandboxConfig(), mcp)
    sandbox.start()
    return sandbox


def test_persistent_namespace():
    sandbox = make_sandbox()
    try:
        assert sandbox.execute("x = 41").output == ""
        assert sandbox.execute("print(x + 1)").output == "42\n"
    finally:
        sandbox.close()


def test_error_is_reported():
    sandbox = make_sandbox()
    try:
        out = sandbox.execute("1/0").output
        assert out == "ERROR: ZeroDivisionError: division by zero"
    finally:
        sandbox.close()


def test_run_tests_tool():
    sandbox = make_sandbox()
    try:
        code = ("print(run_tests(code='def f(): return 1', "
                "test_list=['assert f()==1']))")
        assert '"success": true' in sandbox.execute(code).output
    finally:
        sandbox.close()


def test_final_answer():
    sandbox = make_sandbox()
    try:
        res = sandbox.execute("final_answer('abc')")
        assert res.final_answer == "abc"
    finally:
        sandbox.close()