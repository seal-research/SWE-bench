#!/usr/bin/env python3

import argparse
import json
import random
import re
import sys
from pathlib import Path

from github import Auth, Github
from tqdm import tqdm


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter PRs that resolve issues for swebench"
    )
    parser.add_argument("--out_dir", type=Path, required=True, help="Output directory path")
    parser.add_argument("--prs_file", type=Path, required=True, help="Path to PRs JSONL file")
    parser.add_argument("--token", type=str, required=True, help="GitHub API token")
    parser.add_argument("--skip_commit_message", action="store_true", help="Skip fetching commit messages (faster)")
    return parser


def extract_resolved_issues(pull: dict) -> list[int]:
    issue_ref_re = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)
    comment_re = re.compile(r"(?s)<!--.*?-->")

    text = (pull.get("title") or "") + "\n" + (pull.get("body") or "")
    text += "\n" + "\n".join(commit["message"] for commit in pull.get("commits", []))
    text = comment_re.sub("", text)

    resolved_issues = set()
    for match in issue_ref_re.finditer(text):
        issue_num = int(match.group(3))
        if issue_num != 0:
            resolved_issues.add(issue_num)

    return list(resolved_issues)


def get_github(token: str) -> Github:
    return Github(auth=Auth.Token(token), per_page=100)


def main(out_dir: Path, prs_file: Path, token: str, skip_commit_message: bool):
    print(" Starting PR filtering for swebench...")
    print(f" Output directory: {out_dir}")
    print(f" PRs file: {prs_file}")
    print(f" Skip commit messages: {skip_commit_message}")

    out_dir.mkdir(parents=True, exist_ok=True)

    repo_match = re.match(r"([\w\-]+)__([\w\-]+)_prs\.jsonl", prs_file.name)
    if not repo_match:
        print(f"❌ Error: Invalid PR file name format: {prs_file.name}")
        sys.exit(1)

    org, repo = repo_match.group(1), repo_match.group(2)
    print(f" Repo: {org}/{repo}")

    gh = get_github(token)
    gh_repo = gh.get_repo(f"{org}/{repo}") if not skip_commit_message else None

    out_path = out_dir / f"{org}__{repo}_filtered_prs.jsonl"

    with open(prs_file, "r", encoding="utf-8") as f_in, open(out_path, "w", encoding="utf-8") as f_out:
        for line in tqdm(f_in, desc="⏳ Filtering PRs"):
            pull = json.loads(line)

            if pull.get("state") != "closed":
                continue

            # Fetch commit messages if needed
            if not skip_commit_message:
                try:
                    pr_obj = gh_repo.get_pull(pull["number"])
                    pull["commits"] = [
                        {
                            "sha": commit.sha,
                            "parents": [parent.sha for parent in commit.parents],
                            "message": commit.commit.message,
                        }
                        for commit in pr_obj.get_commits()
                    ]
                except Exception as e:
                    print(f"⚠️ Skipping PR #{pull['number']} due to API error: {e}")
                    continue
            else:
                pull["commits"] = []

            resolved_issues = extract_resolved_issues(pull)
            if resolved_issues:
                pull["resolved_issues"] = resolved_issues
                f_out.write(json.dumps(pull) + "\n")

    print(f"✅ Done. Filtered PRs saved to {out_path}")


if __name__ == "__main__":
    args = get_parser().parse_args()
    main(args.out_dir, args.prs_file, args.token, args.skip_commit_message)
