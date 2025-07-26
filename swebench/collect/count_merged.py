import json

merged = 0
with open("spring-boot-prs.jsonl") as f:
    for line in f:
        pr = json.loads(line)
        if pr.get("merged_at") is not None:
            merged += 1

print(f"Merged PRs: {merged}")

