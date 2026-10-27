# 贡献指南

感谢你愿意为 mnemosyne-mcp 出力。这份文档说明**怎么把改动送进主干**。

## 快速判断表

| 你的改动 | 需要做什么 |
|---|---|
| 修 Bug | 先写一个会失败的测试，再改实现。提交信息写「现象 → 根因 → 修法」 |
| 加功能 | 先在 Issue 里说清「想解决什么问题」，避免方向跑偏后返工 |
| 改检索评分 / 时间衰减 / 归档策略 | **必须在 PR 里说明行为差异与依据** —— 这直接影响 Agent 看到什么 |
| 改时间戳处理 | **必须保持统一格式**（见下方「时间戳约定」） |
| 改文档 | 同步检查 README 承诺的 API 与实际是否一致（历史上出过一次不一致） |
| 只想改措辞 | 直接改，不必先开 Issue |

## 开发环境

```bash
git clone https://github.com/CodeCoreLab/mnemosyne-mcp.git
cd mnemosyne-mcp
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"
```

需要 Python **3.10+**（用了 `X | Y` 类型语法与 `tuple[...]` 泛型下标）。

### 可选附加依赖

```bash
pip install -e ".[sse]"           # SSE 传输（starlette + uvicorn）
pip install -e ".[embeddings]"     # 向量嵌入（规划中能力）
pip install -e ".[sqlite-vec]"     # sqlite-vec 扩展
```

## 跑测试与静态检查

```bash
pytest tests/ -v --tb=short   # 全部测试
pytest tests/ -v -k triple    # 只跑某个主题
ruff check src/ tests/        # 静态检查
```

本地跑测试前需要 `pip install -e ".[dev]"`（`pytest-asyncio` 提供
`asyncio_mode` 配置项，缺失时 pytest 会告警）。

## 时间戳约定（重要）

**所有时间戳必须走 `core._now_iso()`**，不要直接调 `datetime.now()`。

原因：库里同时存在过三种格式 —— Python 本地 naive ISO（`2026-01-01T00:00:00`）、
SQLite `datetime('now')`（UTC，空格分隔 `2026-01-01 00:00:00`）、
带时区的 ISO。三者做**字符串比较**结果不可靠，时序过滤因此会静默出错。

约定：
- 写入用 `_now_iso()`（UTC，ISO 8601 带时区偏移）
- 读取用 `_parse_ts()`，它保证返回 aware datetime（旧数据按 UTC 补齐）
- SQL 里做时间比较用 `datetime(col)` 归一化，不要直接比字符串

## 架构约定

```
core.py
├── 数据模型        MemoryRecord / GraphEdge
├── 工具函数        _now_iso / _parse_ts / _make_id
├── Client          MnemosyneClient（全部业务逻辑）
├── 工具定义        _TOOL_DEFS / TOOLS
├── 路由            _dispatch（工具名 → Client 方法）
├── Server          create_server（stdio / SSE）
└── CLI             main
```

三条硬约定：

1. **Client 不依赖 MCP** —— 纯 Python 使用者不应被迫装 `mcp` 包。
   `mcp` 只在 `create_server` 里按需 import。
2. **工具路由只有一处** —— `_dispatch` 是工具名到 Client 方法的唯一映射。
   加新工具时同步更新 `_TOOL_DEFS` 与 `_dispatch`，两处都要改。
3. **模块导入方向单向** —— `core.py` 不 import 包内其他模块；
   `client.py` 只是转发到 `core.py` 的兼容层。

## 提交信息

用中文，格式：

```
<type>(<scope>): <一句话>

<为什么改 / 现象是什么>

<怎么修的>
```

`<type>` 取值：`feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf` / `build`
`<scope>` 取值：`core` / `client` / `server` / `cli` / `tools` / `docs` / `ci` / `deps`

例：

```
fix(core): 统一时间戳格式，修掉时序过滤的静默错误

现象：triple_query(as_of=...) 过滤结果不对。

根因：valid_from 存的是 SQLite 的 datetime('now')（空格分隔 UTC），
valid_until 存的是 Python 的本地 naive ISO，两者做字符串比较时
'2026-01-01 00:00:00' < '2026-01-01T00:00:00'，时序语义完全错乱。

修法：所有写入统一走 _now_iso()，比较前用 SQLite datetime() 归一化。
```

## PR 要求

- [ ] 测试全绿（`pytest tests/ -v`）
- [ ] 静态检查通过（`ruff check src/ tests/`）
- [ ] 新增功能同步更新 README 的工具表
- [ ] 改过行为的话，在 PR 里说明**行为差异**（旧行为 → 新行为 → 依据）
- [ ] 修 Bug 的话，附上复现步骤与根因分析
