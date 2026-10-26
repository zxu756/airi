import time

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8791/mcp"


async def main() -> None:
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            print("tools:", sorted(names))
            assert names == {"web_search", "web_fetch"}, names

            started = time.monotonic()
            search = await session.call_tool(
                "web_search",
                {"query": "AIRI moeru ai", "count": 3},
            )
            search_seconds = time.monotonic() - started
            search_text = search.content[0].text
            print(search_text[:800])
            assert "Engine: brave" in search_text or "Engine: bing" in search_text, search_text[:200]
            assert "github.com/moeru-ai/airi" in search_text, search_text[:500]
            assert search_seconds < 8, search_seconds

            started = time.monotonic()
            fetch = await session.call_tool(
                "web_fetch",
                {"url": "https://github.com/moeru-ai/airi", "max_chars": 2000},
            )
            fetch_seconds = time.monotonic() - started
            fetch_text = fetch.content[0].text
            print(fetch_text[:800])
            assert "AIRI" in fetch_text, fetch_text[:200]
            assert "<untrusted_content>" in fetch_text, fetch_text[:200]
            assert fetch_seconds < 8, fetch_seconds

            print(f"search {search_seconds:.2f}s, fetch {fetch_seconds:.2f}s")


if __name__ == "__main__":
    anyio.run(main)
