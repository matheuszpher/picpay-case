"""Chama a tool `extract_entities` do servidor MCP diretamente, em processo (sem
spawnar subprocesso via stdio, sem `--command`/`--input-json` na linha de comando).

Existe porque a alternativa (`fastmcp call --command "... -m src.mcp_server.server"
--input-json '{"text": "..."}'`) exige aspas aninhadas na linha de comando, e como
diferentes versões do PowerShell (5.1 vs 7.x) escapam essas aspas de forma diferente
ao repassar o argumento para um `.exe`, o mesmo comando falha em algumas máquinas e
funciona em outras. Aqui só existe um argumento simples (o texto), sem aspas
aninhadas, então o comando funciona igual em qualquer terminal (bash, PowerShell 5.1,
PowerShell 7+).

Uso:
    python scripts/test_mcp.py "Can you send $45 to Michael on June 3?"
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import Client

from src.mcp_server.server import mcp

DEFAULT_TEXT = "Send $100 to John tomorrow."


async def main(text: str) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("extract_entities", {"text": text})
        entities = result.structured_content["result"]
        print(json.dumps(entities, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
    asyncio.run(main(text))
