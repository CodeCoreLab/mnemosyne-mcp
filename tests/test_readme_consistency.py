"""README 与实现的一致性契约测试。

背景：本项目历史上出过一次「README 承诺的 API 不存在」的问题
（`mnemosyne_mcp.client` 模块已被合并进 `core.py`，
 `client.batch()` 从未实现，`remember(tags=...)` 参数不存在），
 用户照着 README 写代码会直接 ImportError / TypeError。

这些测试把「文档承诺」变成**可断言的契约**，防止复发。
"""

import re
from pathlib import Path

import pytest

from mnemosyne_mcp import TOOLS
from mnemosyne_mcp.core import _TOOL_DEFS, MnemosyneClient

README = Path(__file__).parent.parent / "README.md"


@pytest.fixture(scope="module")
def readme_text() -> str:
    assert README.exists(), "README.md 不存在"
    return README.read_text(encoding="utf-8")


class TestReadmeImportsResolve:
    """README 里出现的 import 必须真的能导入。"""

    def test_readme_exists(self, readme_text):
        assert len(readme_text) > 100, "README 内容异常短"

    def test_all_readme_imports_resolve(self, readme_text):
        """抽出 README 里所有 `from X import Y` 形式，逐个验证可导入。"""
        import importlib

        pattern = re.compile(r"from\s+([\w.]+)\s+import\s+([\w,\s]+?)(?=\n|$)")
        checked = 0
        for module_name, names in pattern.findall(readme_text):
            if not module_name.startswith("mnemosyne"):
                continue
            stmt = f"from {module_name} import {names.strip()}"
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"README 中的 `{stmt}` 无法导入: {e}")
            for name in [n.strip() for n in names.split(",") if n.strip()]:
                if not hasattr(module, name):
                    pytest.fail(
                        f"README 中的 `{stmt}` —— `{module_name}` 没有导出 `{name}`"
                    )
                checked += 1
        assert checked > 0, "README 里没找到可检查的 import 语句"

    def test_package_all_entries_importable(self):
        """包级 __all__ 里的每一项都必须真的存在。"""
        import mnemosyne_mcp

        for name in mnemosyne_mcp.__all__:
            assert hasattr(mnemosyne_mcp, name), f"__all__ 声明了不存在的 {name}"

    def test_compat_client_module_exports(self):
        """兼容模块 client.py 必须转发出核心 API。"""
        from mnemosyne_mcp import client as compat

        for name in ("MnemosyneClient", "create_server", "TOOLS"):
            assert hasattr(compat, name), f"兼容模块缺少 {name}"


class TestReadmeApiBehaves:
    """README 里描述的用法必须真的能跑通。"""

    def test_batch_atomic_write(self, tmp_path):
        """README 承诺 batch 是原子操作 —— 验证成功路径。"""
        client = MnemosyneClient(path=tmp_path / "t.db")
        results = client.batch([
            {"action": "remember", "content": "用户偏好 Python", "scope": "global"},
            {"action": "triple_add", "subject": "user", "predicate": "prefers", "object": "Python"},
        ])
        assert len(results) == 2
        assert "memory_id" in results[0]
        assert "id" in results[1]

    def test_batch_rolls_back_on_failure(self, tmp_path):
        """任一条失败必须整批回滚，不留半截数据。"""
        client = MnemosyneClient(path=tmp_path / "t.db")
        with pytest.raises(ValueError):
            client.batch([
                {"action": "remember", "content": "会成功的那条"},
                {"action": "完全不存在的动作"},
            ])
        # 第一条不该留下来
        assert client.stats()["working_count"] == 0

    def test_remember_has_no_tags_parameter(self, tmp_path):
        """README 旧版写过 tags=[...]，实现里没有这个参数 —— 确认仍不支持。"""
        import inspect

        sig = inspect.signature(MnemosyneClient.remember)
        assert "tags" not in sig.parameters

    def test_tool_count_matches_readme(self, readme_text):
        """README 声明的工具总数必须与实现一致。"""
        actual = len(_TOOL_DEFS)
        assert actual == len(TOOLS)
        match = re.search(r"工具总数\s*\*\*(\d+)\*\*", readme_text)
        if match:
            assert int(match.group(1)) == actual, (
                f"README 声称 {match.group(1)} 个工具，实际 {actual} 个"
            )

    def test_every_tool_name_in_readme(self, readme_text):
        """每个工具都应该在 README 的表格里出现。"""
        missing = [d["name"] for d in _TOOL_DEFS if d["name"] not in readme_text]
        assert not missing, f"以下工具未在 README 中列出: {missing}"

    def test_sync_tools_marked_as_placeholder(self, readme_text):
        """占位实现必须在 README 里被如实标注，不能装作能用。"""
        for name in ("mnemosyne_sync_pull", "mnemosyne_sync_push"):
            assert name in readme_text
        assert "占位实现" in readme_text, "README 未标注 sync 工具是占位实现"

    def test_sleep_is_not_summarization(self, tmp_path):
        """sleep() 只归档不摘要 —— 归档条数必须与实际改动一致。"""
        client = MnemosyneClient(path=tmp_path / "t.db")
        for _ in range(3):
            client.remember("低重要性", importance=0.1, scope="session")
        result = client.sleep(force=True)
        assert result["session_consolidated"] == 3
        assert result["eligible"] == 3
        assert client.stats()["episodic_count"] == 3


class TestTimestampConsistency:
    """时间戳格式必须统一 —— 混用会让时序过滤静默出错。"""

    def test_all_written_timestamps_are_utc_with_tz(self, tmp_path):
        client = MnemosyneClient(path=tmp_path / "t.db")
        mem_id = client.remember("测试")
        row = client.get(mem_id)
        assert row is not None
        created = row["created_at"]
        assert created.endswith("+00:00"), f"created_at 缺时区信息: {created}"
        assert "T" in created, f"created_at 不是 ISO 格式: {created}"

    def test_triple_valid_from_uses_same_format(self, tmp_path):
        client = MnemosyneClient(path=tmp_path / "t.db")
        client.triple_add("a", "b", "c")
        rows = client.triple_query(subject="a")
        assert rows
        valid_from = rows[0]["valid_from"]
        assert valid_from.endswith("+00:00"), f"valid_from 缺时区信息: {valid_from}"

    def test_recall_handles_legacy_naive_timestamps(self, tmp_path):
        """旧库里的 naive 时间戳不能导致 recall 抛 TypeError。"""
        import sqlite3

        client = MnemosyneClient(path=tmp_path / "t.db")
        client.remember("旧格式记忆")
        # 手工塞一条升级前的 naive 格式数据
        with sqlite3.connect(str(client.db_path)) as conn:
            conn.execute(
                "INSERT INTO memories (id, memory_id, content, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                ("legacy1", "legacy1", "naive 时间戳的记忆", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
        # 不应抛 TypeError
        results = client.recall("naive", limit=5)
        assert isinstance(results, list)

    def test_temporal_query_filters_correctly(self, tmp_path):
        """as_of 过滤必须真的按时间语义工作。"""
        client = MnemosyneClient(path=tmp_path / "t.db")
        client.triple_add("s", "p", "o")
        # 一个遥远的过去 —— 三元组此时尚未生效，应查不到
        assert client.triple_query(subject="s", as_of="2020-01-01T00:00:00") == []
        # 一个遥远的未来 —— 应查得到
        assert len(client.triple_query(subject="s", as_of="2099-01-01T00:00:00")) == 1


class TestCliWorks:
    """CLI 必须真的能跑（历史上 sys 未导入导致无子命令时崩溃）。"""

    @staticmethod
    def _run_cli(*args):
        """跑 CLI 子进程。

        两个坑：
        1. encoding 必须显式指定 —— Windows 默认用 GBK 解码子进程输出，
           而 CLI 会打印中文，GBK 解码 UTF-8 字节流会抛 UnicodeDecodeError，
           测试自身崩溃，掩盖真实结果。
        2. 环境变量不能整个替换 —— 只设 PATH 会让 Python 找不到
           Winsock 组件（asyncio 依赖），报
           OSError: [WinError 10106] 无法加载或初始化请求的服务提供程序。
           正确做法是在原环境上叠加。
        """
        import os
        import subprocess
        import sys

        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-m", "mnemosyne_mcp.core", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )

    def test_cli_no_subcommand_exits_cleanly(self):
        result = self._run_cli()
        assert "NameError" not in result.stderr, f"CLI 抛 NameError: {result.stderr}"
        assert "Traceback" not in result.stderr, f"CLI 崩溃: {result.stderr}"

    def test_cli_init_creates_db(self, tmp_path):
        db_path = tmp_path / "cli.db"
        result = self._run_cli("init", "--path", str(db_path))
        assert result.returncode == 0, f"init 失败: {result.stderr}"
        assert db_path.exists()
