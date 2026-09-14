"""mnemosyne-mcp 基础使用示例。"""

from mnemosyne_mcp import MnemosyneClient

client = MnemosyneClient(path="./demo_memory.db")

# 1. 写入记忆
user_pref = client.remember(
    content="用户偏好 Python 和简洁代码",
    memory_type="user",
    importance=0.9,
    scope="global",
    metadata={"category": "preference"},
)
print(f"写入记忆: {user_pref}")

# 2. 检索
results = client.recall("Python 偏好", limit=3)
print(f"\n检索结果 ({len(results)} 条):")
for r in results:
    print(f"  [{r['_score']:.3f}] {r['content'][:60]}")

# 3. 知识图谱
client.triple_add("user", "prefers", "Python")
client.triple_add("user", "prefers", "Rust")
client.triple_add("user", "dislikes", "Java")
print("\n知识图谱查询:")
for t in client.triple_query(subject="user"):
    print(f"  user --[{t['predicate']}]--> {t['object']}")

# 4. 记忆链接
proj_id = client.remember("project alpha: FastAPI + React", scope="global", importance=0.8)
tech_id = client.remember("技术栈: FastAPI", scope="global")
client.graph_link(proj_id, tech_id, "uses", weight=0.9)
print("\n图谱遍历:")
for edge in client.graph_query(seed_id=proj_id, max_hops=2):
    print(f"  {edge['from'][:12]} --[{edge['relationship']}]--> {edge['to'][:12]}")

# 5. 统计
print("\n记忆库统计:")
print(client.stats())

# 6. 记忆蒸馏（dry run）
print("\nConsolidate (dry run):")
print(client.sleep(dry_run=True))
