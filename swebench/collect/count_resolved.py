import json

has_issues = 0
with open("spring-boot-prs.jsonl") as f:
    for line in f:
        pr = json.loads(line)
        if pr.get("resolved_issues") and pr["resolved_issues"] != ["0000"]:
            has_issues += 1

print(f"PRs with resolved issues: {has_issues}")

