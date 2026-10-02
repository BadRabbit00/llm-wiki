import asyncio
import json
import os
import sys
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from wikisvc.config import Settings
from wikisvc.services.auth import Auth
from wikisvc.storage.state_db import StateDB


def test_mcp_stdio_lifecycle(config: Settings) -> None:
    auth = Auth(StateDB(config.state_dir))
    token = auth.create("mcp-agent", "writer", "restricted")

    async def run() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "wikisvc.cli", "mcp"],
            env={
                **os.environ,
                "WIKI_ROOT": str(config.wiki_root),
                "STATE_DIR": str(config.state_dir),
                "INDEX_DIR": str(config.index_dir),
                "WIKI_TOKEN": token,
            },
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert len(tools) == 15 and not any(
                "accept" in name or "reject" in name for name in tools
            )

            async def call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
                result = await session.call_tool(name, arguments or {})
                assert not result.isError, result
                return dict(result.structuredContent or json.loads(result.content[0].text))

            instructions = await call("get_instructions")
            assert "недоверенные" in instructions["instructions"]
            assert (await call("search", {"q": "выгрузки счетов"}))["results"]
            assert (await call("get_context", {"id": "app-example-1"}))["pages"]
            assert (await call("get_page", {"id": "app-example-1"}))["id"] == "app-example-1"
            assert (await call("neighbors", {"id": "app-example-1"}))["nodes"]
            assert (await call("read_source_text", {"path": "raw/docs/example.txt"}))[
                "trust"
            ] == "untrusted_external"
            assert "items" in await call("list_pending_sources")
            assert (await call("get_page_template", {"type": "term"}))["prefix"] == "term"
            pid = (await call("create_proposal", {"title": "MCP change"}))["pid"]
            await call(
                "put_page",
                {
                    "pid": pid,
                    "id": "term-mcp",
                    "frontmatter": {
                        "id": "term-mcp",
                        "type": "term",
                        "title": "MCP термин",
                        "summary": "Определение понятия, созданное клиентом через MCP.",
                    },
                    "body_md": "## Определение\n\nПроверка протокола.",
                },
            )
            await call(
                "patch_page",
                {
                    "pid": pid,
                    "id": "term-mcp",
                    "ops": [
                        {
                            "op": "append_to_section",
                            "heading": "Определение",
                            "text": "Дополнительные сведения.",
                        }
                    ],
                },
            )
            assert not (await call("validate_proposal", {"pid": pid}))["errors"]
            assert (await call("submit_proposal", {"pid": pid}))["status"] == "submitted"
            assert (await call("lint"))["issues"]
            auth.revoke("mcp-agent")
            assert (await session.call_tool("search", {"q": "счета"})).isError

    asyncio.run(run())
    assert not (config.wiki_root / "wiki/domain/glossary/mcp.md").exists()
