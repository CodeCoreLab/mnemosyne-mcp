"""
mnemosyne-mcp — AI 记忆管理 MCP Server

核心 API 导出：
  - MnemosyneClient: 纯 Python 客户端（无需 MCP）
  - create_server: MCP Server 工厂函数
  - TOOLS: 工具定义列表

快速开始:
    from mnemosyne_mcp import MnemosyneClient
    client = MnemosyneClient(path="./memory.db")
    mem_id = client.remember("用户偏好 Python", importance=0.9)

兼容说明:
    0.1.x 的 `mnemosyne_mcp.client` / `mnemosyne_mcp.server` / `mnemosyne_mcp.tools`
    三个子模块已在 0.2.0 合并为 `mnemosyne_mcp.core`。
    这里保留 `mnemosyne_mcp.client` 作为兼容别名 —— 旧代码
    `from mnemosyne_mcp.client import MnemosyneClient` 仍可正常工作。
"""

from mnemosyne_mcp.core import (
    TOOLS,
    GraphEdge,
    MemoryRecord,
    MnemosyneClient,
    create_server,
)

__all__ = [
    "TOOLS",
    "GraphEdge",
    "MemoryRecord",
    "MnemosyneClient",
    "create_server",
]

__version__ = "0.2.0"
