"""兼容模块 —— 0.2.0 起实现已合并到 :mod:`mnemosyne_mcp.core`。

0.1.x 曾把客户端放在 ``mnemosyne_mcp.client``，2.0.0 的重构把它和
server / tools 合并进了 ``mnemosyne_mcp.core``。本模块保留为别名，
让旧代码 ``from mnemosyne_mcp.client import MnemosyneClient`` 继续可用。

新代码请直接用::

    from mnemosyne_mcp import MnemosyneClient
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
