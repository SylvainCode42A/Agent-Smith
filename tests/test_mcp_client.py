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