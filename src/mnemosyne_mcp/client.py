"""
mnemosyne-mcp — 纯 Python 客户端

不依赖 MCP 协议，直接操作 SQLite 记忆库。
适合脚本、测试、或嵌入其他框架使用。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
        for r in rows:
            d = dict(r)
            content = d.get("content", "")
            # 简易 BM25 评分
            q_terms = query.lower().split()
            c_terms = content.lower().split()
            score = sum(c_terms.count(t) / (c_terms.count(t) + 0.5 + 1.5 * len(c_terms) / max(len(c_terms), 1)) for t in q_terms if c_terms)
            # 时间衰减
            created = datetime.fromisoformat(d.get("created_at", now.isoformat()))
            age_hours = (now - created).total_seconds() / 3600
            decay = 0.5 ** (age_hours / temporal_halflife)
            final = (vec_weight * score + fts_weight * score + importance_weight * d.get("importance", 0.5)) * (1 + temporal_weight * decay)
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
        """运行记忆 consolidate 周期（模拟：统计 + 时间衰减报告）。"""
        with _get_conn(self.db_path) as c:
            total = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_type = dict(c.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type").fetchall())
            old = c.execute(
                "SELECT COUNT(*) FROM memories WHERE datetime(created_at) < datetime('now', '-30 days')"
            ).fetchone()[0]
        return {
            "total": total,
            "by_type": by_type,
            "older_than_30d": old,
            "dry_run": dry_run,
            "message": f"{'[DRY RUN] ' if dry_run else ''}consolidated: {old} memories older than 30d flagged for review",
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
