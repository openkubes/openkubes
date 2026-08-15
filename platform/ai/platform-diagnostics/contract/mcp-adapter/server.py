"""Thin MCP transport adapter for the ADR-021 HTTP/OpenAPI contract."""
from __future__ import annotations

import os
import uuid

import httpx
from mcp.server.fastmcp import FastMCP

from generated_contract import INVOCATION_ID_HEADER, REQUEST_ID_HEADER, register_tools

FACADE_URL = os.getenv(
    "FACADE_URL",
    "http://platform-diagnostics.platform-diagnostics.svc.cluster.local:8080",
).rstrip("/")
# A real diagnosis runs an LLM + read-only tool calls behind the contract (30-120s).
HTTP_TIMEOUT = float(os.getenv("FACADE_TIMEOUT_SECONDS", "300"))
DIAGNOSTICS_BEARER_TOKEN = os.getenv("DIAGNOSTICS_BEARER_TOKEN", "").strip()
if not DIAGNOSTICS_BEARER_TOKEN:
    raise RuntimeError("DIAGNOSTICS_BEARER_TOKEN is required")

mcp = FastMCP(
    "platform-diagnostics",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8080")),
)


async def _call(path: str, body: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {DIAGNOSTICS_BEARER_TOKEN}",
        REQUEST_ID_HEADER: f"mcp-{uuid.uuid4().hex}",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{FACADE_URL}{path}", json=body, headers=headers)
        resp.raise_for_status()
        result = resp.json()
        header_invocation_id = resp.headers.get(INVOCATION_ID_HEADER)
        if not header_invocation_id:
            raise RuntimeError(
                f"provider response is missing required {INVOCATION_ID_HEADER}"
            )
        if result.get("invocation_id") != header_invocation_id:
            raise RuntimeError(
                "provider response invocation_id does not match its transport header"
            )
        return result


register_tools(mcp, _call)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
