#!/usr/bin/env python3
"""OK-202: localhost-only Streamable HTTP MCP handshake smoke test.

Requires: pip install -r requirements-mcp.txt
Requires: OPENKUBES_DOCS_INDEX=/path/to/index.json
No cluster, ingress, or Ollama access; launches and terminates its own subprocess.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HOST = "127.0.0.1"
PORT = 18080
URL = f"http://{HOST}:{PORT}/mcp"


def unwrap_results(result):
    """Handle MCP SDK response variants (structured or text content)."""
    if result.isError:
        raise AssertionError(f"docs_search returned tool error: {result.content}")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and "result" in structured:
        structured = structured["result"]
    if isinstance(structured, dict) and "results" in structured:
        return structured["results"]
    for item in result.content:
        raw = getattr(item, "text", None)
        if raw:
            decoded = json.loads(raw)
            if isinstance(decoded, dict) and "results" in decoded:
                return decoded["results"]
    raise AssertionError("MCP tool response missing results")


async def check_server() -> None:
    async with streamablehttp_client(URL, timeout=5) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            assert names == ["docs_search"], f"Unexpected tool surface: {names}"
            result = await session.call_tool(
                "docs_search",
                arguments={"query": "How do I install ok-local?", "limit": 5},
            )
            hits = unwrap_results(result)
            assert hits, "No hits for the known install question"
            first = hits[0]
            assert first["repo"] == "openkubes/ok-local", first
            assert first["path"] == "docs/tutorial-basic.md", first
            assert first["url"].startswith(
                "https://github.com/openkubes/ok-local/blob/"
            ), first
            print("PASS HTTP initialize; tools/list=['docs_search']")
            print(f"PASS HTTP tools/call docs_search; {len(hits)} hits")
            print(f"TOP SOURCE: {first['url']}")


async def main() -> None:
    index_name = os.environ.get("OPENKUBES_DOCS_INDEX")
    if not index_name or not Path(index_name).is_file():
        raise SystemExit("Set OPENKUBES_DOCS_INDEX to an existing local index")
    env = os.environ.copy()
    env.update({
        "OPENKUBES_DOCS_INDEX": str(Path(index_name).resolve()),
        "OPENKUBES_MCP_TRANSPORT": "streamable-http",
        "OPENKUBES_MCP_HOST": HOST,
        "OPENKUBES_MCP_PORT": str(PORT),
    })
    server = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parent / "docs_mcp.py")],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server process to be ready; a failed startup is reported.
        # Avoid infinite retries: localhost test deadline is about 15 seconds.
        last_error = None
        for _ in range(20):
            if server.poll() is not None:
                raise RuntimeError(f"MCP server exited with code {server.returncode}")
            try:
                await check_server()
                return
            except (OSError, ConnectionError, TimeoutError) as exc:
                last_error = exc
                await asyncio.sleep(0.5)
        raise RuntimeError(f"HTTP MCP connection did not become ready: {last_error}")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
