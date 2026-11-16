"""Read-only end-to-end test: start the server over stdio MCP and call a few tools.

    python tests/mcp_client_test.py
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "zoom_mcp", "server.py")


async def main():
    params = StdioServerParameters(command=sys.executable, args=[os.path.abspath(SERVER)])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            for name in ("device_info", "list_patches"):
                res = await s.call_tool(name, {})
                print(f"--- {name}\n{res.content[0].text}")

asyncio.run(main())
