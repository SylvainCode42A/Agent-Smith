import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command="python", args=["mcp_tools_mbpp.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            res = await session.call_tool(
                "run_tests",
                {"code": "def f(): return 1", "test_list": ["assert f()==1"]},
            )
            print(res.content[0].text)

asyncio.run(main())