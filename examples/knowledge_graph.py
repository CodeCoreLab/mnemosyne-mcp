"""mnemosyne-mcp 知识图谱高级示例。"""

from datetime import datetime, timedelta

from mnemosyne_mcp import MnemosyneClient

client = MnemosyneClient(path="./demo_graph.db")

# 构建技术栈知识图谱
triples = [
    ("user", "expert_in", "Python"),
    ("user", "expert_in", "DevOps"),
    ("project:alpha", "uses", "FastAPI"),
    ("project:alpha", "uses", "React"),
    ("project:alpha", "deployed_on", "AWS"),
    ("project:beta", "uses", "Rust"),
    ("project:beta", "uses", "Axum"),
    ("project:beta", "deployed_on", "GCP"),
    ("FastAPI", "built_with", "Python"),
    ("React", "built_with", "TypeScript"),
    ("AWS", "provider_of", "EC2"),
    ("AWS", "provider_of", "S3"),
    ("GCP", "provider_of", "GKE"),
]

for s, p, o in triples:
    client.triple_add(s, p, o)

print("=== 知识图谱 ===")
print("\n用户技能:")
for t in client.triple_query(subject="user", predicate="expert_in"):
    print(f"  {t['object']}")

print("\nProject Alpha 技术栈:")
for t in client.triple_query(subject="project:alpha"):
    print(f"  alpha --[{t['predicate']}]--> {t['object']}")

print("\nAWS 提供的服务:")
for t in client.triple_query(subject="AWS", predicate="provider_of"):
    print(f"  {t['object']}")

# 写入项目记忆并建立链接
p1 = client.remember("Project Alpha: 中台巡检系统，FastAPI + React，部署 AWS", scope="global", importance=0.9)
p2 = client.remember("Project Beta: Rust 微服务，Axum + GKE", scope="global", importance=0.8)

client.graph_link(p1, p1, "about", weight=1.0)  # self-ref

# 通过项目名查找记忆并遍历关联
print("\n=== 记忆图遍历 (Project Alpha) ===")
edges = client.graph_query(seed_id=p1, max_hops=2, min_weight=0.5)
for e in edges[:5]:
    print(f"  [{e['relationship']}] {e['from'][:16]} -> {e['to'][:16]} (hops={e['hops']})")

# 历史回溯查询
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
# 假设 valid_until 是昨天，可以查到当时有效的三元组
old_triples = client.triple_query(subject="AWS", as_of=yesterday)
print(f"\n{yesterday} 时 AWS 相关的三元组: {len(old_triples)} 条")
