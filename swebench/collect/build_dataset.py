#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
from typing import Optional

from swebench.collect.utils import (
    extract_patches,
    extract_problem_statement_and_hints,
    Repo,
)

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Test Detection Patterns ---
TEST_FILE_PATTERNS = [
    re.compile(r'src[/\\]test[/\\]'),
    re.compile(r'[/\\]test[s]?[/\\]'),
    re.compile(r'.*Test[s]?\.(java|kt|py)$'),
    re.compile(r'integration[-_]?test[s]?'),
    re.compile(r'[/\\]it[/\\]'),
    re.compile(r'pom\.xml$'),
    re.compile(r'build\.gradle$'),
]

# Additional test content patterns
TEST_CONTENT_PATTERNS = [
    re.compile(r'\bassert\w*\b', re.IGNORECASE),
    re.compile(r'@Test\b'),
    re.compile(r'import\s+org\.junit'),
    re.compile(r'import\s+org\.mockito'),
    re.compile(r'Assertions?\.'),
    re.compile(r'import\s+static\s+org\.junit'),
    re.compile(r'\bverify\s*\('),
]


def is_test_related_path(path: str) -> bool:
    normalized_path = path.lower().replace('\\', '/')
    return any(p.search(normalized_path) for p in TEST_FILE_PATTERNS)


def has_test_patch(instance: dict) -> bool:
    test_patch = instance.get("test_patch", "").strip()
    patch = instance.get("patch", "").strip()

    if not test_patch and not patch:
        logger.debug("Both test_patch and patch are empty")
        return False

    combined_patch = f"{test_patch}\n{patch}".strip()

    for line in combined_patch.splitlines():
        line = line.strip()

        # Check file paths in diff headers
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    file_path = parts[2][2:] if parts[2].startswith("b/") else parts[2]
                    if is_test_related_path(file_path):
                        logger.info(f"✅ Detected test file change: {file_path}")
                        return True
                except IndexError:
                    continue

        # Check content of additions/deletions
        if line.startswith(('+', '-')):
            for pattern in TEST_CONTENT_PATTERNS:
                if pattern.search(line):
                    logger.info(f"✅ Detected test content in line: {line}")
                    return True

    logger.debug("❌ No test-related files or content found in test_patch or patch.")
    return False



def create_instance(repo: Repo, pull: dict) -> dict:
    patch, test_patch = extract_patches(pull, repo)
    logger.debug(f"[PR #{pull['number']}] Extracted patch: {len(patch)} chars, test_patch: {len(test_patch)} chars")

    problem_statement, hints = extract_problem_statement_and_hints(pull, repo)
    return {
        "repo": repo.repo.full_name,
        "pull_number": pull["number"],
        "instance_id": (repo.repo.full_name + "-" + str(pull["number"])).replace("/", "__"),
        "issue_numbers": pull["resolved_issues"],
        "base_commit": pull["base"]["sha"],
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": problem_statement,
        "hints_text": hints,
        "created_at": pull["created_at"],
    }


def is_valid_pull(pull: dict) -> bool:
    return pull["merged_at"] is not None and bool(pull.get("resolved_issues"))


def is_valid_instance(instance: dict) -> bool:
    return bool(instance.get("patch")) and bool(instance.get("problem_statement"))


def main(pr_file: str, output: str, token: Optional[str] = None):
    if token is None:
        token = os.environ.get("GITHUB_TOKEN")

    def load_repo(repo_name):
        owner, repo = repo_name.split("/")
        return Repo(owner, repo, token=token)

    repos = {}
    completed = 0
    with_tests = 0
    total_instances = 0
    skipped_prs = 0
    all_output_path = output + ".all"
    seen_prs = set()

    if os.path.exists(all_output_path):
        with open(all_output_path) as f:
            for line in f:
                pr = json.loads(line)
                if "instance_id" not in pr:
                    pr["instance_id"] = (pr["repo"] + "-" + str(pr["pull_number"])).replace("/", "__")
                seen_prs.add(pr["instance_id"])
                if is_valid_instance(pr):
                    completed += 1
                    if has_test_patch(pr):
                        with_tests += 1

    logger.info(f"Will skip {len(seen_prs)} previously processed PRs")

    write_mode_all = "a" if os.path.exists(all_output_path) else "w"
    write_mode_filtered = "a" if os.path.exists(output) else "w"

    with open(all_output_path, write_mode_all) as all_output, open(output, write_mode_filtered) as filtered_output:
        for ix, line in enumerate(open(pr_file)):
            total_instances += 1
            pull = json.loads(line)

            if ix % 100 == 0:
                logger.info(f"[{pull['base']['repo']['full_name']}] (Up to {ix}) {completed} valid, {with_tests} with tests.")

            instance_id = (pull["base"]["repo"]["full_name"] + "-" + str(pull["number"])).replace("/", "__")
            if instance_id in seen_prs:
                seen_prs.remove(instance_id)
                continue

            if not is_valid_pull(pull):
                skipped_prs += 1
                continue

            repo_name = pull["base"]["repo"]["full_name"]
            if repo_name not in repos:
                repos[repo_name] = load_repo(repo_name)

            repo = repos[repo_name]
            instance = create_instance(repo, pull)

            if is_valid_instance(instance):
                print(json.dumps(instance), file=all_output, flush=True)
                completed += 1

                if has_test_patch(instance):
                    print(json.dumps(instance), file=filtered_output, flush=True)
                    with_tests += 1
                else:
                    logger.debug(f"[PR #{pull['number']}] ❌ No test patch found.")
            else:
                logger.debug(f"[PR #{pull['number']}] ❌ Invalid instance.")

    logger.info(f"[{', '.join(repos.keys())}] Total instances processed: {total_instances}")
    logger.info(f"[{', '.join(repos.keys())}] Valid instances: {completed}, With tests: {with_tests}")
    logger.info(f"[{', '.join(repos.keys())}] Skipped {skipped_prs} PRs without issues or merge")
    logger.info(f"[{', '.join(repos.keys())}] Skipped {len(seen_prs)} PRs previously processed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_file", type=str, help="Path to pull request JSONL file")
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument("--token", type=str, help="GitHub token")
    args = parser.parse_args()
    main(**vars(args))

