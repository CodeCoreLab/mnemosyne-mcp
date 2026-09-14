"""mnemosyne-mcp 工具路由测试（无需 MCP 依赖）。"""

import json
import tempfile
from pathlib import Path

import pytest

from mnemosyne_mcp.client import MnemosyneClient
from mnemosyne_mcp.server import _dispatch


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

    def test_unknown_tool(self, client: MnemosyneClient):
        result = _dispatch(client, "nonexistent_tool", {})
        assert "error" in result
