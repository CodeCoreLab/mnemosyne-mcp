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
"""

from mnemosyne_mcp.core import MnemosyneClient, MemoryRecord, GraphEdge, create_server

__all__ = [
    "MnemosyneClient",
    "MemoryRecord",
    "GraphEdge",
    "create_server",
]

__version__ = "0.2.0"
