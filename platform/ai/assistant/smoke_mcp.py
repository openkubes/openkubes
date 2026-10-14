#!/usr/bin/env python3
"""Exercise a real MCP stdio handshake/list/call without kagent or Kubernetes.

Requires: pip install -r requirements-mcp.txt
Requires: OPENKUBES_DOCS_INDEX=/path/to/an/approved/index.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check() -> None:
    index_path = Path(os.environ.get("OPENKUBES_DOCS_INDEX", "")).expanduser()
    if not index_path.is_file():
        raise SystemExit("Set OPENKUBES_DOCS_INDEX to a built, local index JSON file")
    env = dict(os.environ)
    env["OPENKUBES_DOCS_INDEX"] = str(index_path.resolve())
    env["OPENKUBES_MCP_TRANSPORT"] = "stdio"
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve().parent / "docs_mcp.py")],
        env=env,
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = sorted(tool.name for tool in listing.tools)
            assert names == ["docs_search"], f"Unexpected tool surface: {names}"
            result = await session.call_tool(
                "docs_search",
                arguments={"query": "How do I install ok-local?", "limit": 5},
            )
            if result.isError:
                raise AssertionError(f"MCP tool error: {result.content}")
            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, dict) and "result" in structured:
                structured = structured["result"]
            if not isinstance(structured, dict) or "results" not in structured:
                chunks = [getattr(item, "text", "") for item in result.content]
                if not chunks:
                    raise AssertionError("MCP response had no structured/text data")
                structured = json.loads(chunks[0])
            hits = structured["results"]
            assert hits, "Expected at least one source hit"
            assert hits[0]["repo"] == "openkubes/ok-local", hits[0]
            assert hits[0]["path"] == "docs/tutorial-basic.md", hits[0]
            print(f"PASS initialize; tools/list={names}")
            print(f"PASS tools/call docs_search; {len(hits)} hits")
            print(f"TOP SOURCE: {hits[0]['url']}")


if __name__ == "__main__":
    asyncio.run(check())
