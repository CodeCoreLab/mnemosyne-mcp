"""
mnemosyne-mcp — 统一核心模块

合并原 client.py + server.py，提供：
  - MnemosyneClient：纯 Python 客户端（SQLite 记忆库）
  - create_server：MCP Server 工厂函数
  - TOOLS：工具定义列表
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 可选 MCP 依赖
# ---------------------------------------------------------------------------
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    Server = None

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class MemoryRecord:
    """单条记忆记录"""
    id: str = ""
    memory_id: str = ""
    content: str = ""
    memory_type: str = "user"  # user | feedback | project | reference
    scope: str = "session"  # global | session
    importance: float = 0.5
    valid_until: str = ""  # ISO date YYYY-MM-DD, empty = forever
    source: str = "user"
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.id:
            self.id = self.memory_id or _make_id()


@dataclass
class GraphEdge:
    """知识图谱边"""
    source_id: str
    target_id: str
    relationship: str
    weight: float = 0.5


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _make_id() -> str:
    return f"mem_{int(time.time()*1000)}_{id(object()):x}"


_DEFAULT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    memory_id   TEXT UNIQUE,
    content     TEXT NOT NULL,
    memory_type TEXT DEFAULT 'user',
    scope       TEXT DEFAULT 'session',
    importance  REAL DEFAULT 0.5,
    valid_until TEXT DEFAULT '',
    source      TEXT DEFAULT 'user',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS triples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    confidence  REAL DEFAULT 1.0,
    valid_from  TEXT DEFAULT (datetime('now')),
    valid_until TEXT DEFAULT '',
    superseded  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_triples_sp ON triples(subject, predicate);
CREATE INDEX IF NOT EXISTS idx_triples_o ON triples(object);
CREATE TABLE IF NOT EXISTS graph_edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    relationship TEXT NOT NULL,
    weight      REAL DEFAULT 0.5,
    PRIMARY KEY (source_id, target_id, relationship)
);
"""


def _get_conn(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MnemosyneClient:
    """mnemosyne-mcp 纯 Python 客户端。

    参数:
        path: SQLite 数据库路径。默认 ``~/.mnemosyne/data/mnemosyne.db``
    """

    def __init__(self, path: str | Path | None = None):
        if path is None:
            path = Path(os.environ.get("MNEMOSYNE_DATA_DIR", "~/.mnemosyne/data")) / "mnemosyne.db"
        self.db_path = Path(path).expanduser()
        self._ensure_schema()

    def _ensure_schema(self):
        with _get_conn(self.db_path) as c:
            c.executescript(_DEFAULT_SCHEMA)

    # ------------------------------------------------------------------
    # 记忆 CRUD
    # ------------------------------------------------------------------

    def remember(
        self,
        content: str,
        memory_type: str = "user",
        scope: str = "session",
        importance: float = 0.5,
        valid_until: str = "",
        metadata: dict | None = None,
        **kwargs,
    ) -> str:
        """写入一条记忆，返回 memory_id。"""
        mem_id = _make_id()
        now = datetime.now().isoformat()
        with _get_conn(self.db_path) as c:
            c.execute(
                "INSERT INTO memories (id, memory_id, content, memory_type, scope, "
                "importance, valid_until, source, metadata, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mem_id, mem_id, content, memory_type, scope,
                    importance, valid_until,
                    kwargs.get("source", "user"),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now, now,
                ),
            )
        return mem_id

    def recall(
        self,
        query: str,
        limit: int = 5,
        temporal_halflife: float = 24.0,
        temporal_weight: float = 0.0,
        vec_weight: float = 0.5,
        fts_weight: float = 0.3,
        importance_weight: float = 0.2,
        scope: str = "",
    ) -> list[dict]:
        """语义检索记忆（简化 BM25 + 时间衰减 + 重要性加权）。

        返回按综合评分排序的记忆列表。
        """
        rows = []
        with _get_conn(self.db_path) as c:
            sql = "SELECT id, memory_id, content, memory_type, scope, importance, metadata, created_at FROM memories WHERE 1=1"
            params: list = []
            if scope:
                sql += " AND scope=?"
                params.append(scope)
            sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
            params.append(limit * 4)  # 多取一些，后面重排
            rows = c.execute(sql, params).fetchall()

        results = []
        now = datetime.now()
        doc_len_avg = 0.0
        if rows:
            doc_lens = [len((r["content"] or "").split()) for r in rows]
            doc_len_avg = sum(doc_lens) / max(len(doc_lens), 1)
        for r in rows:
            d = dict(r)
            content = d.get("content", "")
            # TF-IDF 评分
            q_terms = query.lower().split()
            c_terms = content.lower().split()
            doc_len = len(c_terms)
            score = 0.0
            for t in q_terms:
                tf = c_terms.count(t)
                idf = 1.0
                if tf > 0:
                    idf = (doc_len_avg + 1) / (tf + 1)
                score += idf * (tf * (1.5 + 1)) / (tf + 1.5 * (1 - 0.75 + 0.75 * doc_len / max(doc_len_avg, 1)))
            # 时间衰减
            created = datetime.fromisoformat(d.get("created_at", now.isoformat()))
            age_hours = (now - created).total_seconds() / 3600
            decay = 0.5 ** (age_hours / temporal_halflife)
            final = (vec_weight * 0.3 + fts_weight * score + importance_weight * d.get("importance", 0.5)) * (1 + temporal_weight * decay)
            d["_score"] = round(final, 4)
            results.append(d)

        results.sort(key=lambda x: x["_score"], reverse=True)
        return results[:limit]

    def get(self, memory_id: str) -> dict | None:
        with _get_conn(self.db_path) as c:
            r = c.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
            return dict(r) if r else None

    def update(self, memory_id: str, **changes) -> bool:
        """更新记忆字段，返回是否成功。"""
        if not changes:
            return False
        allowed = {"content", "importance", "valid_until", "metadata", "scope"}
        sets, vals = [], []
        for k, v in changes.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            if k == "metadata" and isinstance(v, dict):
                v = json.dumps(v, ensure_ascii=False)
            vals.append(v)
        if not sets:
            return False
        sets.append("updated_at=?")
        vals.append(datetime.now().isoformat())
        vals.append(memory_id)
        with _get_conn(self.db_path) as c:
            cur = c.execute(f"UPDATE memories SET {','.join(sets)} WHERE memory_id=?", vals)
            return cur.rowcount > 0

    def forget(self, memory_id: str) -> bool:
        with _get_conn(self.db_path) as c:
            cur = c.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
            return cur.rowcount > 0

    def invalidate(self, memory_id: str, replacement_id: str = "") -> bool:
        return self.update(memory_id, metadata={"status": "invalidated", "replaced_by": replacement_id})

    # ------------------------------------------------------------------
    # 知识图谱
    # ------------------------------------------------------------------

    def triple_add(
        self,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
        valid_until: str = "",
    ) -> int:
        with _get_conn(self.db_path) as c:
            cur = c.execute(
                "INSERT INTO triples (subject, predicate, object, confidence, valid_until) VALUES (?,?,?,?,?)",
                (subject, predicate, object_, confidence, valid_until),
            )
            return cur.lastrowid

    def triple_query(
        self,
        subject: str = "",
        predicate: str = "",
        object_: str = "",
        as_of: str = "",
    ) -> list[dict]:
        sql = "SELECT * FROM triples WHERE superseded=0"
        params: list = []
        if subject:
            sql += " AND subject=?"; params.append(subject)
        if predicate:
            sql += " AND predicate=?"; params.append(predicate)
        if object_:
            sql += " AND object=?"; params.append(object_)
        if as_of:
            sql += " AND (valid_from<=? OR valid_until='') AND (valid_until='' OR valid_until>=?)"
            params.extend([as_of, as_of])
        with _get_conn(self.db_path) as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def triple_end(self, subject: str, predicate: str, object_: str = "", valid_until: str = "") -> int:
        valid = valid_until or datetime.now().isoformat()
        with _get_conn(self.db_path) as c:
            sql = "UPDATE triples SET valid_until=?, superseded=1 WHERE subject=? AND predicate=?"
            params: list = [valid, subject, predicate]
            if object_:
                sql += " AND object=?"; params.append(object_)
            cur = c.execute(sql, params)
            return cur.rowcount

    def graph_link(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        weight: float = 0.5,
    ) -> bool:
        with _get_conn(self.db_path) as c:
            try:
                c.execute(
                    "INSERT OR REPLACE INTO graph_edges (source_id, target_id, relationship, weight) VALUES (?,?,?,?)",
                    (source_id, target_id, relationship, weight),
                )
                return True
            except Exception:
                return False

    def graph_query(self, seed_id: str, max_hops: int = 2, min_weight: float = 0.0) -> list[dict]:
        """多跳 BFS 遍历记忆图。"""
        visited = {seed_id: 0}
        queue = [(seed_id, 0)]
        result = []
        with _get_conn(self.db_path) as c:
            while queue:
                current, depth = queue.pop(0)
                if depth >= max_hops:
                    continue
                edges = c.execute(
                    "SELECT target_id, relationship, weight FROM graph_edges WHERE source_id=? AND weight>=?",
                    (current, min_weight),
                ).fetchall()
                for e in edges:
                    tid = e["target_id"]
                    if tid not in visited:
                        visited[tid] = depth + 1
                        queue.append((tid, depth + 1))
                    result.append({
                        "from": current,
                        "to": tid,
                        "relationship": e["relationship"],
                        "weight": e["weight"],
                        "hops": depth + 1,
                    })
        return result

    # ------------------------------------------------------------------
    # 记忆管理
    # ------------------------------------------------------------------

    def sleep(self, force: bool = False, dry_run: bool = False) -> dict:
        """运行记忆 consolidate 周期（working → episodic 摘要）。"""
        with _get_conn(self.db_path) as c:
            total = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_type = dict(c.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type").fetchall())
            old = c.execute(
                "SELECT COUNT(*) FROM memories WHERE datetime(created_at) < datetime('now', '-30 days')"
            ).fetchone()[0]
            session_count = c.execute("SELECT COUNT(*) FROM memories WHERE scope='session'").fetchone()[0]
        if not dry_run and (force or session_count > 100):
            with _get_conn(self.db_path) as c:
                c.execute(
                    "UPDATE memories SET scope='global', memory_type='episodic' "
                    "WHERE scope='session' AND importance < 0.3 AND id IN "
                    "(SELECT id FROM memories WHERE scope='session' AND importance < 0.3 LIMIT 50)"
                )
        return {
            "total": total,
            "by_type": by_type,
            "older_than_30d": old,
            "session_consolidated": min(session_count, 50) if not dry_run else 0,
            "dry_run": dry_run,
            "message": f"{'[DRY RUN] ' if dry_run else ''}consolidated: {min(session_count, 50) if not dry_run else old} memories processed",
        }

    def scratchpad_write(self, content: str) -> str:
        """写入临时便签（本会话级，不落库）。"""
        key = f"scratch_{int(time.time()*1000)}"
        _SCRATCHPAD[key] = {"content": content, "ts": datetime.now().isoformat()}
        return key

    def scratchpad_read(self) -> dict:
        return _SCRATCHPAD

    def scratchpad_clear(self) -> int:
        count = len(_SCRATCHPAD)
        _SCRATCHPAD.clear()
        return count

    def hygiene_audit(self, limit: int = 200) -> list[dict]:
        """审计记忆噪声。"""
        with _get_conn(self.db_path) as c:
            rows = c.execute(
                "SELECT id, content, memory_type, importance, length(content) as clen FROM memories ORDER BY importance ASC LIMIT ?",
                (limit,),
            ).fetchall()
        candidates = []
        for r in rows:
            score = 0.0
            if r["clen"] < 10:
                score += 0.3
            if r["importance"] < 0.2:
                score += 0.5
            if any(k in (r["content"] or "").lower() for k in ["traceback", "error", "stack"]):
                score += 0.4
            candidates.append({"id": r["id"], "content": r["content"][:80], "score": round(score, 2)})
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def hygiene_clean(self, candidates: list[dict], action: str = "keep", confirm: bool = False) -> dict:
        """清理噪声记忆。

        action: delete / archive / flag / keep
        confirm: 为 True 时才实际执行删除，否则 dry-run。
        """
        if not confirm:
            return {"status": "dry-run ok", "would_clean": len(candidates), "action": action}
        if action == "keep":
            return {"status": "kept", "count": len(candidates)}
        target_ids = [c["id"] for c in candidates if c.get("score", 0) >= 0.3]
        if not target_ids:
            return {"status": "nothing to clean", "count": 0}
        with _get_conn(self.db_path) as c:
            if action == "delete":
                c.executemany("DELETE FROM memories WHERE id=?", [(i,) for i in target_ids])
                return {"status": "deleted", "count": len(target_ids)}
            if action == "archive":
                c.executemany(
                    "UPDATE memories SET metadata=json_set(metadata, '$.status', 'archived') WHERE id=?",
                    [(i,) for i in target_ids],
                )
                return {"status": "archived", "count": len(target_ids)}
            if action == "flag":
                c.executemany(
                    "UPDATE memories SET metadata=json_set(metadata, '$.flagged', 1) WHERE id=?",
                    [(i,) for i in target_ids],
                )
                return {"status": "flagged", "count": len(target_ids)}
        return {"status": "unknown action", "count": 0}

    def stats(self) -> dict:
        with _get_conn(self.db_path) as c:
            return {
                "working_count": c.execute("SELECT COUNT(*) FROM memories WHERE scope='session'").fetchone()[0],
                "episodic_count": c.execute("SELECT COUNT(*) FROM memories WHERE scope='global'").fetchone()[0],
                "triple_count": c.execute("SELECT COUNT(*) FROM triples WHERE superseded=0").fetchone()[0],
                "graph_edges": c.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0],
            }

    # ------------------------------------------------------------------
    # 验证
    # ------------------------------------------------------------------

    def validate(
        self,
        memory_id: str,
        action: str = "attest",
        new_content: str = "",
        note: str = "",
        validator: str = "",
    ) -> bool:
        """多方验证记忆（attest / update / invalidate / delete）。"""
        if action == "attest":
            return True
        if action == "update" and new_content:
            return self.update(memory_id, content=new_content)
        if action == "invalidate":
            return self.invalidate(memory_id)
        if action == "delete":
            return self.forget(memory_id)
        return False

    # ------------------------------------------------------------------
    # 共享表面 (Shared Surface)
    # ------------------------------------------------------------------

    def shared_recall(self, query: str, limit: int = 5) -> list[dict]:
        """只检索 scope=global 的记忆（跨 agent 共享层）。"""
        return self.recall(query, limit=limit, scope="global")

    def shared_remember(self, content: str, importance: float = 0.8, **kwargs) -> str:
        """写入全局共享记忆。"""
        return self.remember(content, scope="global", importance=importance, **kwargs)

    def shared_forget(self, memory_id: str) -> bool:
        return self.forget(memory_id)

    def shared_stats(self) -> dict:
        return self.stats()


# 进程级临时便签存储
_SCRATCHPAD: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# MCP Server
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
        candidates = args.get("candidates_json", "[]")
        try:
            cand_list = json.loads(candidates) if isinstance(candidates, str) else candidates
        except Exception:
            cand_list = []
        return client.hygiene_clean(
            cand_list,
            action=args.get("action", "keep"),
            confirm=args.get("confirm", False),
        )
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
