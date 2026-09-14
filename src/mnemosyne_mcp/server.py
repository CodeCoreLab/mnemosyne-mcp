"""
mnemosyne-mcp — MCP Server 入口

支持 stdio（Claude Desktop 默认）和 SSE（远程访问）两种传输模式。

用法:
    # stdio (默认)
    mnemosyne-mcp serve

    # SSE 本地回环
    mnemosyne-mcp serve --transport sse --port 8080

    # SSE LAN 暴露（需 token）
    MNEMOSYNE_MCP_TOKEN=secret mnemosyne-mcp serve --transport sse --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, CallToolResult, ErrorData
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    Server = None

from mnemosyne_mcp.client import MnemosyneClient


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------

_TOOL_DEFS: list[dict[str, Any]] = [
    # --- 记忆 CRUD ---
    {
        "name": "mnemosyne_remember",
        "description": "写入一条记忆。支持 memory_type (user/feedback/project/reference)、importance、scope、valid_until。",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆内容"},
                "memory_type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                "scope": {"type": "string", "enum": ["global", "session"]},
                "importance": {"type": "number", "minimum": 0, "maximum": 1},
                "valid_until": {"type": "string", "description": "ISO 日期 YYYY-MM-DD，空=永久"},
                "metadata": {"type": "object"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "mnemosyne_recall",
        "description": "语义检索记忆（hybrid 评分：向量 + FTS5 + 重要性 + 时间衰减）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "temporal_halflife": {"type": "number", "default": 24},
                "temporal_weight": {"type": "number", "default": 0},
                "scope": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mnemosyne_get",
        "description": "按 memory_id 精确读取记忆。",
        "input_schema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "mnemosyne_update",
        "description": "更新已有记忆字段（content / importance / metadata 等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "content": {"type": "string"},
                "importance": {"type": "number"},
                "metadata": {"type": "object"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "mnemosyne_forget",
        "description": "按 memory_id 永久删除记忆。",
        "input_schema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "mnemosyne_invalidate",
        "description": "标记记忆为过期/被取代，可指定 replacement_id。",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "replacement_id": {"type": "string"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "mnemosyne_validate",
        "description": "多方验证记忆：attest / update / invalidate / delete。",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "action": {"type": "string", "enum": ["attest", "update", "invalidate", "delete"]},
                "new_content": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["memory_id", "action"],
        },
    },
    # --- 知识图谱 ---
    {
        "name": "mnemosyne_triple_add",
        "description": "写入三元组 (subject, predicate, object)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "confidence": {"type": "number", "default": 1.0},
                "valid_until": {"type": "string"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "mnemosyne_triple_query",
        "description": "查询三元组，支持 subject/predicate/object 过滤和历史回溯 (as_of)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "as_of": {"type": "string", "description": "ISO 日期，查询该时刻有效的三元组"},
            },
        },
    },
    {
        "name": "mnemosyne_triple_end",
        "description": "让三元组失效（设置 valid_until，保留审计链路）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "valid_until": {"type": "string"},
            },
            "required": ["subject", "predicate"],
        },
    },
    {
        "name": "mnemosyne_graph_link",
        "description": "在两条记忆间声明语义关系（weight 0.0-1.0）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "relationship": {"type": "string"},
                "weight": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["source_id", "target_id", "relationship"],
        },
    },
    {
        "name": "mnemosyne_graph_query",
        "description": "多跳 BFS 遍历记忆图（max_hops / min_weight）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "seed_memory_id": {"type": "string"},
                "edge_type": {"type": "string"},
                "max_hops": {"type": "integer", "default": 2},
                "min_weight": {"type": "number", "default": 0},
            },
            "required": ["seed_memory_id"],
        },
    },
    # --- 记忆管理 ---
    {
        "name": "mnemosyne_sleep",
        "description": "运行 consolidate 周期：旧 working memory → episodic 摘要，防止上下文爆炸。",
        "input_schema": {
            "type": "object",
            "properties": {
                "all_sessions": {"type": "boolean", "default": False},
                "force": {"type": "boolean", "default": False},
                "dry_run": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "mnemosyne_scratchpad_write",
        "description": "写入临时便签（进程级，不持久化）。",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    },
    {
        "name": "mnemosyne_scratchpad_read",
        "description": "读取当前所有临时便签。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "mnemosyne_scratchpad_clear",
        "description": "清空所有临时便签。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "mnemosyne_hygiene_audit",
        "description": "审计记忆噪声（terminal spam / secret / stack trace / 低重要性）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200},
                "min_score": {"type": "number", "default": 0.3},
            },
        },
    },
    {
        "name": "mnemosyne_hygiene_clean",
        "description": "清理噪声记忆（delete / archive / flag / keep）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates_json": {"type": "string"},
                "action": {"type": "string", "enum": ["delete", "archive", "flag", "keep"], "default": "keep"},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["candidates_json"],
        },
    },
    {
        "name": "mnemosyne_stats",
        "description": "记忆库统计（working / episodic / triples / graph_edges 数量）。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "mnemosyne_sync_pull",
        "description": "从远程同步服务器拉取记忆变更。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "mnemosyne_sync_push",
        "description": "推送本地记忆变更到远程同步服务器。",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def create_server(db_path: str | Path | None = None) -> "Server":
    """创建 Mnemosyne MCP Server 实例。"""
    if not _MCP_AVAILABLE:
        raise RuntimeError("mcp package not installed. Run: pip install mnemosyne-mcp")

    client = MnemosyneClient(path=db_path)
    server = Server("mnemosyne-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**d) for d in _TOOL_DEFS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = _dispatch(client, name, arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
        except Exception as e:
            logger.error("tool %s error: %s", name, e)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

    return server


def _dispatch(client: MnemosyneClient, name: str, args: dict) -> Any:
    """路由工具调用到 Client 方法。"""
    # 记忆 CRUD
    if name == "mnemosyne_remember":
        return {"memory_id": client.remember(
            content=args["content"],
            memory_type=args.get("memory_type", "user"),
            scope=args.get("scope", "session"),
            importance=args.get("importance", 0.5),
            valid_until=args.get("valid_until", ""),
            metadata=args.get("metadata"),
        )}
    if name == "mnemosyne_recall":
        return client.recall(
            query=args["query"],
            limit=args.get("limit", 5),
            temporal_halflife=args.get("temporal_halflife", 24),
            temporal_weight=args.get("temporal_weight", 0),
            scope=args.get("scope"),
        )
    if name == "mnemosyne_get":
        return client.get(args["memory_id"]) or {"error": "not found"}
    if name == "mnemosyne_update":
        return {"success": client.update(args["memory_id"], **{k: v for k, v in args.items() if k != "memory_id"})}
    if name == "mnemosyne_forget":
        return {"success": client.forget(args["memory_id"])}
    if name == "mnemosyne_invalidate":
        return {"success": client.invalidate(args["memory_id"], args.get("replacement_id", ""))}
    if name == "mnemosyne_validate":
        return {"success": client.validate(
            args["memory_id"], args["action"],
            new_content=args.get("new_content", ""),
            note=args.get("note", ""),
            validator=args.get("validator", ""),
        )}
    # 知识图谱
    if name == "mnemosyne_triple_add":
        return {"id": client.triple_add(
            args["subject"], args["predicate"], args["object"],
            args.get("confidence", 1.0), args.get("valid_until", ""),
        )}
    if name == "mnemosyne_triple_query":
        return client.triple_query(
            subject=args.get("subject", ""),
            predicate=args.get("predicate", ""),
            object_=args.get("object", ""),
            as_of=args.get("as_of", ""),
        )
    if name == "mnemosyne_triple_end":
        return {"affected": client.triple_end(
            args["subject"], args["predicate"],
            args.get("object", ""), args.get("valid_until", ""),
        )}
    if name == "mnemosyne_graph_link":
        return {"success": client.graph_link(
            args["source_id"], args["target_id"],
            args["relationship"], args.get("weight", 0.5),
        )}
    if name == "mnemosyne_graph_query":
        return client.graph_query(
            seed_id=args["seed_memory_id"],
            max_hops=args.get("max_hops", 2),
            min_weight=args.get("min_weight", 0),
        )
    # 记忆管理
    if name == "mnemosyne_sleep":
        return client.sleep(force=args.get("force", False), dry_run=args.get("dry_run", False))
    if name == "mnemosyne_scratchpad_write":
        return {"key": client.scratchpad_write(args["content"])}
    if name == "mnemosyne_scratchpad_read":
        return client.scratchpad_read()
    if name == "mnemosyne_scratchpad_clear":
        return {"cleared": client.scratchpad_clear()}
    if name == "mnemosyne_hygiene_audit":
        return client.hygiene_audit(args.get("limit", 200))
    if name == "mnemosyne_hygiene_clean":
        return {"status": "dry-run ok" if not args.get("confirm") else "cleaned"}
    if name == "mnemosyne_stats":
        return client.stats()
    if name == "mnemosyne_sync_pull":
        return {"status": "pulled", "note": "requires remote sync server"}
    if name == "mnemosyne_sync_push":
        return {"status": "pushed", "note": "requires remote sync server"}
    return {"error": f"unknown tool: {name}"}


# ---------------------------------------------------------------------------
# 传输层
# ---------------------------------------------------------------------------

def _loopback_only() -> tuple[str, str | None]:
    host = os.environ.get("MNEMOSYNE_HOST", "127.0.0.1")
    token = os.environ.get("MNEMOSYNE_MCP_TOKEN", "")
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise RuntimeError(
            f"Refusing to bind non-loopback host {host!r} without MNEMOSYNE_MCP_TOKEN"
        )
    return host, token or None


async def _stdio_loop():
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def _sse_loop(host: str, port: int):
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.requests import Request
        import uvicorn
    except ImportError as e:
        raise RuntimeError(f"SSE transport requires extra deps: {e}")

    _, token = _loopback_only()
    server = create_server()
    sse = SseServerTransport(f"http://{host}:{port}/messages")

    async def handle_sse(request: Request):
        if token:
            auth = request.headers.get("authorization", "")
            if f"Bearer {token}" not in auth:
                from starlette.responses import PlainTextResponse
                return PlainTextResponse("unauthorized", status_code=401)
        async with sse.connect_sse(request.scope, request.receive, request.send) as streams:
            await server.run(*streams, server.create_initialization_options())

    async def handle_messages(request: Request):
        await sse.handle_post_message(request.scope, request.receive, request.send)

    app = Starlette(routes=[
        Route("/sse", handle_sse, methods=["GET"]),
        Route("/messages", handle_messages, methods=["POST"]),
    ])
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser("mnemosyne-mcp")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="启动 MCP Server")
    serve_p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    serve_p.add_argument("--host", default=os.environ.get("MNEMOSYNE_HOST", "127.0.0.1"))
    serve_p.add_argument("--port", type=int, default=int(os.environ.get("MNEMOSYNE_PORT", "8080")))
    serve_p.add_argument("--path", help="SQLite 数据库路径")

    init_p = sub.add_parser("init", help="初始化记忆库")
    init_p.add_argument("--path", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        p = Path(args.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        client = MnemosyneClient(path=p)
        print(f"Initialized: {p}")
        print(json.dumps(client.stats(), indent=2))
        return

    if args.command == "serve":
        if args.transport == "stdio":
            asyncio.run(_stdio_loop())
        else:
            asyncio.run(_sse_loop(args.host, args.port))


if __name__ == "__main__":
    main()
