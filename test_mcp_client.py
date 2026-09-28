"""Self-test: connects to mcp_server.py over stdio, lists tools, calls a few."""
import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            for name, args in (
                ("get_stats", {}),
                ("get_settings", {}),
                ("update_setting", {"key": "min_abs_profit", "value": "0.3"}),
                ("update_setting", {"key": "hacker_key", "value": "x"}),
            ):
                res = await session.call_tool(name, args)
                print(f"\n--- {name} ---\n{res.content[0].text}")


asyncio.run(main())