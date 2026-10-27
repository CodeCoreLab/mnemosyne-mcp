# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-27

本次是**修复性大版本**：0.1.0 存在多个导致「装不上 / 跑不起来 / 文档与实现不符」的问题。

### 修复

- **修复 `pip install` 必然失败**：原声明依赖 `mnemosyne>=3.15.0`，
  而 PyPI 上 `mnemosyne` 最高只有 `0.1.0` —— 该约束永远无法满足。
  实际上本项目是纯 SQLite 实现，从未 import 过 `mnemosyne`。
  现已移除该依赖，`sqlite-vec` 移入可选附加依赖
- **修复 CI workflow 从未成功过**：`.github/workflows/ci.yml` 里
  `pip install -e ".[dev]` 的引号未闭合，YAML 把后续内容吞成字符串，
  shell 会把 `".[dev]` 当成包名去 PyPI 查找 —— 必然失败
- **修复 `mnemosyne-mcp` 不带子命令时崩溃**：`main()` 里调用
  `sys.exit(1)`，但 `sys` 从未导入，抛 `NameError: name 'sys' is not defined`
- **修复时间戳格式混用导致时序过滤静默出错**：
  `triples.valid_from` 存的是 SQLite `datetime('now')`（UTC、空格分隔），
  `valid_until` 存的是 Python 本地 naive ISO（`T` 分隔），
  两者做**字符串比较**时 `' ' < 'T'`，`valid_from <= ?` 的语义完全错乱。
  现所有写入统一走 `_now_iso()`（UTC + 时区偏移），
  SQL 比较前用 `datetime(col)` 归一化
- **修复 `recall()` 的时间衰减可能抛 TypeError**：
  库中旧数据是不带时区的 naive ISO，与 aware 的 `now` 相减会抛
  "can't subtract offset-naive and offset-aware datetimes"。
  现统一用 `_parse_ts()` 解析，naive 值按 UTC 补齐
- **修复 `hygiene_clean` 的 `candidates_json` 解析失败被静默吞掉**：
  非法 JSON 会返回空列表，调用方误以为「没有需要清理的」，
  而真实原因是自己的 JSON 写错了。现直接抛 `ValueError`
- **修复 `graph_link` 吞掉所有异常**：改为只捕获 `sqlite3.Error` 并记日志，
  避免掩盖非数据库类的真实错误
- **修复 LICENSE 无法被 GitHub 识别**：原先是手写的 15 行摘要片段，
  换成 apache.org 官方 202 行全文
- **修复 `sleep()` 报告的数字前后不一致**：
  `session_consolidated` 报的是 session 总数、message 报的是 30 天前数量，
  两者语义不同却混用。现统一为实际 consolidate 的条数，
  并补充 `session_count` / `eligible` 字段
- **修复 `pyproject.toml` 版本号与 `__init__.py` 不一致**（0.1.0 vs 0.2.0）

### 新增

- **`MnemosyneClient.batch()`** —— README 承诺但从未实现的批量原子写入。
  单个事务执行，任一条失败整批回滚并抛异常，不留半截数据。
  支持 `remember` / `triple_add` / `graph_link` / `update` / `forget`
- **`mnemosyne_mcp.client` 兼容模块** —— 0.2.0 把实现合并进 `core.py`，
  但 README 与旧代码仍在 `from mnemosyne_mcp.client import ...`。
  现保留为转发别名，旧代码无需修改
- **`TOOLS` 公开导出** —— 包级文档一直承诺导出 `TOOLS`，
  但只有私有的 `_TOOL_DEFS`
- **`_now_iso()` / `_parse_ts()`** —— 统一的时间戳读写入口
- 治理文件：`CONTRIBUTING.md` / `SECURITY.md` / `CODE_OF_CONDUCT.md` / `ROADMAP.md`
- Issue 模板（Bug / 功能建议）与 PR 模板
- CI 增加 `smoke` job：验证包能装上、CLI 能跑、`import` 可用

### 变更

- **PyPI 发布改为手动触发**（`workflow_dispatch`）。
  原因：PyPI 上的 `mnemosyne-mcp` 已被他人占用
  （castnettech/mnemosyne，0.1.0 / 0.2.0），自动发布会在 main 推送时
  尝试抢注同名包 —— 既会失败，也可能造成混淆。
  确需发布时先确认包名可用，或改用新包名
- 许可证声明改为 PEP 639 写法（`license = "Apache-2.0"` + `license-files`），
  移除与 license 表达式重复的 `License ::` classifier
  （setuptools>=77 遇到重复会直接抛 `InvalidConfigError`）
- `pyproject.toml` 显式锁定 ruff 规则集 —— 原先未声明 `select`，
  生效规则集随 ruff 版本漂移，CI 会出现「今天绿、升个 ruff 就红」
- 依赖精简：移除未使用的 `mnemosyne`，`sqlite-vec` / `embeddings` / `sse` 归入可选组
- README 全面校准：`client` 模块、`batch()`、`tags` 参数、
  工具数（17 → 21）、记忆层级（3 级 → 2 级 scope）、
  检索方式（语义 → 关键词）、架构树、依赖说明
- 明确标注未实现能力：`sync_pull` / `sync_push` 是占位实现，
  `sleep()` 只归档不摘要，向量检索未接入

### 已知限制

- 中文检索效果差 —— `query.lower().split()` 按空格切词，
  中文句子会被切成一整段，BM25 基本失效（已列入 ROADMAP P2）
- 记忆库明文存储，不含加密（详见 SECURITY.md）

## [0.1.0] - 2026-09-15

### Added

- Initial release of `mnemosyne-mcp`
- `MnemosyneClient`: pure Python SQLite client
- MCP server: stdio + SSE transport
- Memory CRUD: remember / recall / get / update / forget / invalidate
- Knowledge graph: triple_add / triple_query / triple_end / graph_link / graph_query
- Memory management: sleep / scratchpad / hygiene_audit / stats
- Shared surface: shared_remember / shared_recall
- CLI: `mnemosyne-mcp serve` / `mnemosyne-mcp init`
