# 安全政策

## 支持的版本

| 版本 | 支持 |
|---|---|
| 0.2.x | ✅ |
| 0.1.x | ❌ 已知安装即失败（依赖 `mnemosyne>=3.15.0` 在 PyPI 上不存在），请升级 |

## 报告漏洞

**请勿用公开 Issue 报告安全漏洞。**

用 GitHub 的私密漏洞报告功能：
[Security → Report a vulnerability](https://github.com/CodeCoreLab/mnemosyne-mcp/security/advisories/new)

或邮件联系维护者。收到报告后我会在 **48 小时内**确认收到，
并给出修复或缓解方案。

| 阶段 | 目标时间 |
|---|---|
| 确认收到 | 48 小时 |
| 初步评估 | 7 天 |
| 发布修复 | 视严重程度，14 天内 |

## 使用本项目的安全须知

### 记忆库是明文文件

SQLite 数据库**不做任何加密**。记忆内容以明文存放在磁盘上。

- 用**加密卷**（如 LUKS、BitLocker、FileVault）存放记忆库
- 或用文件系统权限限制访问（`chmod 600`）
- 备份同样包含明文，按敏感数据对待

### 记忆内容会被 MCP 客户端看到

MCP Server 把记忆内容原样返回给客户端（Claude Desktop / Cursor 等）。
如果记忆里存了凭据、内部地址、用户隐私，**这些内容会离开你的机器**。
写入前自行判断，或用 `mnemosyne_hygiene_clean` 定期清理。

### SSE 模式的网络暴露

- 默认绑定 **loopback**（127.0.0.1），局域网内不可达
- 绑定非 loopback 地址时**必须**设置 `MNEMOSYNE_MCP_TOKEN`，
  否则启动时直接拒绝（`_loopback_only()`）
- 令牌用 `Authorization: Bearer <token>` 头传递
- SSE **没有 TLS**，跨主机暴露请放在反向代理后面

```bash
# 启动带令牌的 SSE
export MNEMOSYNE_MCP_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export MNEMOSYNE_HOST=0.0.0.0
mnemosyne-mcp serve --transport sse --port 8080
```

### 删除操作不可逆

`mnemosyne_hygiene_clean` 的 `action="delete"` 是**物理删除**，无撤销、无回收站。
- 默认是 dry-run，必须显式 `confirm=True` 才真删
- 删除只作用于 `score >= 0.3` 的候选
- 删除前建议先备份数据库文件

### 归档 ≠ 压缩

`mnemosyne_sleep()` 做的只是把记忆的 `scope` / `memory_type` 改一下，
**不生成任何摘要**。上下文并不会因此变短。
真正需要压缩上下文时，得自己接 LLM 做摘要。

## 已知限制

| 限制 | 说明 |
|---|---|
| 无内容加密 | 见上 |
| 无访问控制 | SQLite 文件权限即全部访问控制 |
| 同步功能是占位实现 | `mnemosyne_sync_pull` / `mnemosyne_sync_push` 不做任何实际同步 |
| SQL 拼接 | `update()` 的字段名来自白名单 `allowed`，值走参数化查询，无注入风险 |
| 单文件数据库 | 不支持并发写入（SQLite 本身限制） |
