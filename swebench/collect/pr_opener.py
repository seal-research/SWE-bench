import json
with open("spring-boot-prs.jsonl") as f:
    for line in f:
        pull = json.loads(line)
        if "resolved_issues" not in pull or not pull["resolved_issues"]:
            print(f"PR #{pull['number']} missing resolved_issues or empty")

