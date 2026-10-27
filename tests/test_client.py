"""mnemosyne-mcp 基础测试。"""

import json
from pathlib import Path

import pytest

from mnemosyne_mcp.core import MnemosyneClient, _make_id


@pytest.fixture
def client(tmp_path: Path) -> MnemosyneClient:
    db = tmp_path / "test_mnemosyne.db"
    return MnemosyneClient(path=db)


class TestIdUniqueness:
    """ID 生成必须唯一。

    早期实现用 `id(object())`（CPython 临时对象内存地址），
    地址回收后会被复用 —— 同一毫秒内连续调用生成完全相同的 ID，
    实测 20000 次调用有 19985 次重复，快速写入必然撞 UNIQUE 约束。
    """

    def test_make_id_unique_in_bulk(self):
        ids = [_make_id() for _ in range(20000)]
        assert len(set(ids)) == len(ids), "ID 生成出现重复"

    def test_consecutive_writes_do_not_collide(self, client: MnemosyneClient):
        """连续写入不撞 UNIQUE 约束 —— 这是曾经真实发生的线上故障。"""
        ids = [client.remember(f"memory-{i}") for i in range(500)]
        assert len(set(ids)) == 500

    def test_id_format(self):
        mid = _make_id()
        assert mid.startswith("mem_")
        assert len(mid) == len("mem_") + 32  # uuid4 hex


class TestMemoryCRUD:
    def test_remember(self, client: MnemosyneClient):
        mid = client.remember("test content", importance=0.9)
        assert mid.startswith("mem_")
        rec = client.get(mid)
        assert rec is not None
        assert rec["content"] == "test content"
        assert rec["importance"] == 0.9

    def test_recall(self, client: MnemosyneClient):
        client.remember("用户偏好 Python", importance=0.8, scope="global")
        client.remember("用户喜欢简洁代码", importance=0.7)
        results = client.recall("Python 偏好", limit=5)
        assert len(results) > 0
        assert all("_score" in r for r in results)
        # 按评分降序
        scores = [r["_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_recall_scoring_prefers_relevant(self, client: MnemosyneClient):
        client.remember("Python 异步编程 asyncio 最佳实践", importance=0.5)
        client.remember("买菜做饭日常生活记录", importance=0.9)
        results = client.recall("Python 编程", limit=2)
        assert results[0]["content"] == "Python 异步编程 asyncio 最佳实践"

    def test_update(self, client: MnemosyneClient):
        mid = client.remember("original")
        ok = client.update(mid, content="updated", importance=1.0)
        assert ok
        rec = client.get(mid)
        assert rec["content"] == "updated"

    def test_forget(self, client: MnemosyneClient):
        mid = client.remember("to be deleted")
        ok = client.forget(mid)
        assert ok
        assert client.get(mid) is None

    def test_invalidate(self, client: MnemosyneClient):
        mid = client.remember("old fact")
        ok = client.invalidate(mid, replacement_id="new_mem_123")
        assert ok
        rec = client.get(mid)
        meta = rec["metadata"]
        # metadata 存储为 JSON 字符串，解析后验证
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("status") == "invalidated"


class TestKnowledgeGraph:
    def test_triple_add_query(self, client: MnemosyneClient):
        tid = client.triple_add("user", "prefers", "Python", confidence=0.9)
        assert tid > 0
        results = client.triple_query(subject="user", predicate="prefers")
        assert len(results) > 0
        assert results[0]["object"] == "Python"

    def test_triple_end(self, client: MnemosyneClient):
        client.triple_add("user", "likes", "coffee")
        count = client.triple_end("user", "likes")
        assert count >= 1

    def test_graph_link_query(self, client: MnemosyneClient):
        m1 = client.remember("memory 1", scope="global")
        m2 = client.remember("memory 2", scope="global")
        ok = client.graph_link(m1, m2, "references", weight=0.8)
        assert ok
        edges = client.graph_query(seed_id=m1, max_hops=2)
        assert len(edges) >= 1
        assert edges[0]["to"] == m2


class TestMemoryManagement:
    def test_sleep(self, client: MnemosyneClient):
        client.remember("short term")
        result = client.sleep(dry_run=True)
        assert "message" in result
        assert "DRY RUN" in result["message"]

    def test_scratchpad(self, client: MnemosyneClient):
        key = client.scratchpad_write("temp note")
        assert key.startswith("scratch_")
        notes = client.scratchpad_read()
        assert key in notes
        cleared = client.scratchpad_clear()
        assert cleared >= 1

    def test_hygiene_audit(self, client: MnemosyneClient):
        client.remember("x", importance=0.1)  # 低重要性
        candidates = client.hygiene_audit(limit=10)
        assert isinstance(candidates, list)

    def test_hygiene_clean_dry_run(self, client: MnemosyneClient):
        result = client.hygiene_clean([{"id": "x", "score": 0.8}], action="delete", confirm=False)
        assert result["status"] == "dry-run ok"

    def test_hygiene_clean_delete(self, client: MnemosyneClient):
        mid = client.remember("to clean", importance=0.1)
        result = client.hygiene_clean([{"id": mid, "score": 0.8}], action="delete", confirm=True)
        assert result["status"] == "deleted"
        assert client.get(mid) is None

    def test_sleep_consolidates(self, client: MnemosyneClient):
        client.remember("session memory", importance=0.1, scope="session")
        result = client.sleep(force=True, dry_run=False)
        assert "session_consolidated" in result

    def test_stats(self, client: MnemosyneClient):
        client.remember("test")
        stats = client.stats()
        assert "working_count" in stats
        assert "episodic_count" in stats
        assert "triple_count" in stats


class TestSharedSurface:
    def test_shared_remember_recall(self, client: MnemosyneClient):
        mid = client.shared_remember("shared knowledge", importance=0.9)
        results = client.shared_recall("knowledge", limit=5)
        assert any(r["memory_id"] == mid for r in results)

    def test_shared_stats(self, client: MnemosyneClient):
        stats = client.shared_stats()
        assert isinstance(stats, dict)
