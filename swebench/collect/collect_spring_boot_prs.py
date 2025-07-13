import os
import re
import json
import logging
from datetime import datetime
from utils import Repo
from fastcore.xtras import obj2dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - spring-boot-collector - %(levelname)s - %(message)s"
)
logger = logging.getLogger("spring-boot-collector")

# Setup GitHub token
token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
if not token:
    raise EnvironmentError("GitHub token not set in GITHUB_TOKEN or GH_TOKEN")

# Initialize repo
repo = Repo("spring-projects", "spring-boot", token=token)

# Output file
output_file = "spring-boot-prs.jsonl"
max_pulls = None  # Optional: set to a number to limit processed PRs
cutoff_date = None  # Format: "20240101"

if cutoff_date:
    cutoff_date = datetime.strptime(cutoff_date, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%SZ")

logger.info(f"Fetching PRs for spring-projects/spring-boot...")
count = 0

def extract_resolved_issues_from_all(pull):
    """
    Extract issue references from PR title, body, and commit messages.
    """
    issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
    comments_pat = re.compile(r"(?s)<!--.*?-->")
    keywords = {
        "close", "closes", "closed",
        "fix", "fixes", "fixed",
        "resolve", "resolves", "resolved",
    }

    text = pull.get("title", "") + "\n" + pull.get("body", "")

    if "commits" in pull:
        text += "\n" + "\n".join([c.get("message", "") for c in pull["commits"]])

    text = comments_pat.sub("", text)

    references = dict(issues_pat.findall(text))
    resolved_issues = set()

    for word, issue_num in references.items():
        if word.lower() in keywords:
            resolved_issues.add(int(issue_num))

    if 0 in resolved_issues:
        resolved_issues.remove(0)

    return list(resolved_issues)

with open(output_file, "w") as fout:
    for i, pull in enumerate(repo.get_all_pulls()):
        try:
            created_at = pull.get("created_at", "")
            if cutoff_date and created_at < cutoff_date:
                logger.info(f"Stopping at PR #{pull['number']} due to cutoff")
                break

            # Fetch commit messages for more accurate issue references
            commits = repo.call_api(
                repo.api.pulls.list_commits,
                owner=repo.owner,
                repo=repo.name,
                pull_number=pull["number"]
            )
            commit_messages = [
                {
                    "message": c["commit"]["message"]
                } for c in commits if "commit" in c and "message" in c["commit"]
            ]
            pull["commits"] = commit_messages

            resolved = extract_resolved_issues_from_all(pull)

            # Fallback to Timeline API if not found
            if not resolved:
                timeline = repo.call_api(
                    repo.api.issues.list_events_for_timeline,
                    owner=repo.owner,
                    repo=repo.name,
                    issue_number=pull["number"]
                )

                timeline_issues = []
                for event in timeline or []:
                    if event.get("event") == "cross-referenced":
                        source = event.get("source", {})
                        issue = source.get("issue", {})
                        if issue.get("pull_request") is None:
                            issue_number = str(issue.get("number"))
                            if issue_number and issue_number not in timeline_issues:
                                timeline_issues.append(issue_number)

                resolved = timeline_issues

            pull["resolved_issues"] = resolved if resolved else []

            if resolved:
                logger.info(f"✅ PR #{pull['number']}: resolved issues {resolved}")
            else:
                logger.warning(f"⚠️  PR #{pull['number']}: no resolved issues found")

            fout.write(json.dumps(obj2dict(pull)) + "\n")
            count += 1

            if max_pulls is not None and count >= max_pulls:
                logger.info(f"Max pulls ({max_pulls}) reached")
                break

        except Exception as e:
            logger.error(f"Failed to process PR #{pull.get('number', '?')} - {e}")

logger.info(f"Done! Total PRs saved: {count}")

