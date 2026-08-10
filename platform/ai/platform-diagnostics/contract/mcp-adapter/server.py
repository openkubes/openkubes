"""Thin MCP transport adapter for the ADR-021 HTTP/OpenAPI contract."""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

from generated_contract import register_tools

FACADE_URL = os.getenv(
    "FACADE_URL",
    "http://platform-diagnostics.platform-diagnostics.svc.cluster.local:8080",
).rstrip("/")
# A real diagnosis runs an LLM + read-only tool calls behind the contract (30-120s).
HTTP_TIMEOUT = float(os.getenv("FACADE_TIMEOUT_SECONDS", "300"))

mcp = FastMCP(
    "platform-diagnostics",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8080")),
)


async def _call(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{FACADE_URL}{path}", json=body)
        resp.raise_for_status()
        return resp.json()


register_tools(mcp, _call)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
