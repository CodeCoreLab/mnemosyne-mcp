# mnemosyne-mcp

> AI Agent 记忆管理 MCP Server — 三级记忆 · 时间衰减 · 语义检索 · 知识图谱

[![CI](https://github.com/CodeCoreLab/mnemosyne-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/CodeCoreLab/mnemosyne-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mnemosyne-mcp)](https://pypi.org/project/mnemosyne-mcp/)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

为 Claude Desktop / Cursor / Windsurf 等 MCP 客户端提供结构化记忆能力。基于 [Mnemosyne](https://github.com/mem0ai/mem0) 架构设计，走**本地优先、SQLite + 知识图谱**路线。

```
记忆层级: working_memory (短期) → episodic_memory (情景) → persona (人格)
检索: hybrid 评分 (vector 50% + FTS5 30% + importance 20%)
图谱: subject-predicate-object 三元组 + 多跳遍历
蒸馏: 长期会话自动 consolidate，防止上下文爆炸
```

---

## 与 mem0 的差异

| 特性 | mem0 | mnemosyne-mcp |
|------|------|---------------|
| 存储 | 需 Qdrant / PGVector | **纯 SQLite，零外部依赖** |
| 检索 | embedding API | **BM25 + sqlite-vec，可选本地 embedding** |
| 知识图谱 | 实体链接 | **三元组 + 时序 + 多跳 BFS** |
| 部署 | 需 Docker / 服务端 | **单文件 `pip install` 即用** |
| 数据所有权 | 云端可选 | **本地 SQLite 文件，100% 可控** |

---

## 快速开始

```bash
# 安装
pip install mnemosyne-mcp

# 初始化记忆库
mnemosyne-mcp init --path ~/.mnemosyne/data

# 启动 MCP Server (stdio)
mnemosyne-mcp serve

# 或 SSE 模式（本地回环）
mnemosyne-mcp serve --transport sse --port 8080
```

### Claude Desktop 配置

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "mnemosyne-mcp",
      "args": ["serve"]
    }
  }
}
```

---

## 核心 API

### 记忆操作

| 工具 | 说明 |
|------|------|
| `mnemosyne_remember` | 写入记忆（user/feedback/project/reference，支持 importance / temporal_halflife） |
| `mnemosyne_recall` | 语义检索（hybrid 评分，支持时间窗口、重要性加权） |
| `mnemosyne_get` | 按 ID 精确读取 |
| `mnemosyne_update` | 更新已有记忆 |
| `mnemosyne_forget` | 按 ID 删除 |
| `mnemosyne_invalidate` | 标记过期/被取代 |
| `mnemosyne_validate` | 多方验证（attest / update / invalidate / delete） |

### 知识图谱

| 工具 | 说明 |
|------|------|
| `mnemosyne_triple_add` | 写入三元组 (subject, predicate, object) |
| `mnemosyne_triple_query` | 图谱查询（支持 as_of 历史回溯） |
| `mnemosyne_triple_end` | 过期三元组（不删除，保留审计链路） |
| `mnemosyne_graph_link` | 显式声明记忆间的语义边 |
| `mnemosyne_graph_query` | 多跳 BFS 遍历（max_hops / min_weight） |

### 记忆管理

| 工具 | 说明 |
|------|------|
| `mnemosyne_sleep` | 运行 consolidate 周期（旧 working → episodic 摘要） |
| `mnemosyne_scratchpad_write` | 临时便签（进程级，不持久化） |
| `mnemosyne_scratchpad_read` | 读取临时便签 |
| `mnemosyne_scratchpad_clear` | 清空临时便签 |
| `mnemosyne_hygiene_audit` | 审计噪声（terminal spam / secret / stack trace） |
| `mnemosyne_hygiene_clean` | 清理噪声（delete / archive / flag） |
| `mnemosyne_stats` | 记忆库统计（working / episodic / BEAM tiers） |
| `mnemosyne_sync_pull` | 从远程同步服务器拉取记忆 |
| `mnemosyne_sync_push` | 推送本地记忆到远程 |

### 批量操作

```python
from mnemosyne_mcp.client import MnemosyneClient

client = MnemosyneClient(path="~/.mnemosyne/data/mnemosyne.db")

# 批量写入（原子操作）
results = client.batch([
    {"action": "remember", "content": "用户偏好 Python", "scope": "global", "importance": 0.9},
    {"action": "triple_add", "subject": "user", "predicate": "prefers", "object": "Python"},
    {"action": "graph_link", "source_id": "...", "target_id": "...", "relationship": "references"},
])
```

---

## Python 直接使用（无需 MCP）

```python
from mnemosyne_mcp.client import MnemosyneClient

client = MnemosyneClient(path="./my_memory.db")

# 写入
mem_id = client.remember(
    content="用户喜欢简洁的代码风格",
    tags=["preference", "coding-style"],
    importance=0.8,
)

# 检索
results = client.recall("代码风格偏好", limit=5)

# 知识图谱
client.triple_add("user", "prefers", "Python", confidence=1.0)
graph = client.graph_query(seed_id=mem_id, max_hops=2)

# 记忆蒸馏
client.sleep(force=True)
```

---

## 架构

```
mnemosyne-mcp/
├── src/mnemosyne_mcp/
│   ├── __init__.py      # 公共 API 导出
│   ├── server.py        # MCP stdio/SSE 服务器
│   ├── client.py        # 纯 Python 客户端（无需 MCP）
│   └── tools.py         # 工具注册 + 路由
├── tests/
│   ├── test_client.py
│   └── test_tools.py
└── examples/
    ├── basic_usage.py
    └── knowledge_graph.py
```

**依赖**: `mnemosyne >= 3.15.0`（核心引擎） + `mcp >= 1.0.0`（协议层）

---

## 数据安全

- 所有记忆存储在本地 SQLite 文件，**不上传任何云端**
- 支持 `MNEMOSYNE_DATA_DIR` 环境变量自定义存储路径
- SSE 模式默认绑定 loopback，LAN 暴露必须设置 `MNEMOSYNE_MCP_TOKEN`
- 支持全量导出（JSON）和增量同步（sync server）

---

## License

Apache-2.0
