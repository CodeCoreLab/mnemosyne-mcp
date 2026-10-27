"""mnemosyne-mcp 工具路由测试（无需 MCP 依赖）。"""

import json
from pathlib import Path

import pytest

from mnemosyne_mcp.core import MnemosyneClient, _dispatch


@pytest.fixture
def client(tmp_path: Path) -> MnemosyneClient:
    return MnemosyneClient(path=tmp_path / "test.db")


class TestDispatch:
    def test_remember(self, client: MnemosyneClient):
        result = _dispatch(client, "mnemosyne_remember", {"content": "hello"})
        assert "memory_id" in result

    def test_recall(self, client: MnemosyneClient):
        _dispatch(client, "mnemosyne_remember", {"content": "test recall"})
        result = _dispatch(client, "mnemosyne_recall", {"query": "test"})
        assert isinstance(result, list)

    def test_triple_flow(self, client: MnemosyneClient):
        r1 = _dispatch(client, "mnemosyne_triple_add", {"subject": "a", "predicate": "b", "object": "c"})
        assert "id" in r1
        r2 = _dispatch(client, "mnemosyne_triple_query", {"subject": "a"})
        assert len(r2) >= 1

    def test_scratchpad(self, client: MnemosyneClient):
        _dispatch(client, "mnemosyne_scratchpad_write", {"content": "note"})
        result = _dispatch(client, "mnemosyne_scratchpad_read", {})
        assert isinstance(result, dict)

    def test_stats_tool(self, client: MnemosyneClient):
        result = _dispatch(client, "mnemosyne_stats", {})
        assert "working_count" in result

    def test_hygiene_clean_tool(self, client: MnemosyneClient):
        client.remember("low importance", importance=0.1)
        audited = client.hygiene_audit(limit=5)
        result = _dispatch(client, "mnemosyne_hygiene_clean", {
            "candidates_json": json.dumps(audited),
            "action": "delete",
            "confirm": True,
        })
        assert result["status"] == "deleted"
        # 必须真的删掉了东西 —— 只断言 status 的话，
        # "删了 0 条" 也会返回 deleted，测试形同虚设
        assert result["count"] >= 1
        assert client.stats()["working_count"] == 0

    def test_hygiene_clean_invalid_json_raises(self, client: MnemosyneClient):
        """candidates_json 非法时必须报错，而不是静默返回空列表。"""
        import pytest

        with pytest.raises(ValueError, match="candidates_json"):
            _dispatch(client, "mnemosyne_hygiene_clean", {
                "candidates_json": "{not valid json",
                "action": "delete",
                "confirm": True,
            })

    def test_unknown_tool(self, client: MnemosyneClient):
        result = _dispatch(client, "nonexistent_tool", {})
        assert "error" in result
