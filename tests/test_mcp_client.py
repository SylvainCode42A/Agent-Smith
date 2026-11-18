from smith_core.sandbox.mcp_client import McpClient


def test_connect_and_call():
    client = McpClient.from_stdio("python mcp_tools_mbpp.py")
    client.connect()
    try:
        assert [t.name for t in client.tools] == ["run_tests"]
        out = client.call_tool("run_tests", {"code": "def f(): return 1",
                                            "test_list": ["assert f()==1"]})
        assert '"success": true' in out
    finally:
        client.close()

def test_resources_and_prompts():
    client = McpClient.from_stdio("python mcp_tools_mbpp.py")
    client.connect()
    try:
        assert [str(r.uri) for r in client.resources] == ["mbpp://guide"]
        assert [p.name for p in client.prompts] == ["solve_task"]
        assert "run_tests" in client.read_resource("mbpp://guide")
        text = client.get_prompt("solve_task", {"task": "add two numbers"})
        assert "add two numbers" in text
    finally:
        client.close()