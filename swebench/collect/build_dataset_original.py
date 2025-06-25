#!/usr/bin/env python3

import argparse
import json
import logging
import os
from typing import Optional
from datetime import datetime


from utils import (
    extract_patches,
    extract_problem_statement_and_hints,
    Repo,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_instance(repo: Repo, pull: dict) -> dict:
    patch, test_patch = extract_patches(pull, repo)
    problem_statement, hints = extract_problem_statement_and_hints(pull, repo)

    # Fetch resolved issue details
    issue_numbers = pull.get("resolved_issues", [])
    resolved_issues = []
    for issue_num in issue_numbers:
        try:
            issue = repo.api.issues.get(owner=repo.owner, repo=repo.name, issue_number=int(issue_num))
            resolved_issues.append({
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "html_url": issue.html_url,
            "created_at": issue.created_at.isoformat() if isinstance(issue.created_at, datetime) else issue.created_at,
            "state": issue.state
            })

        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch issue #{issue_num} - {e}")

    return {
        "repo": repo.repo.full_name,
        "pull_number": pull["number"],
        "instance_id": (repo.repo.full_name + "-" + str(pull["number"])).replace("/", "__"),
        "resolved_issues": resolved_issues,  # <--- updated
        "base_commit": pull["base"]["sha"],
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": problem_statement,
        "hints_text": hints,
        "created_at": pull["created_at"],
    }



def is_valid_pull(pull: dict) -> bool:
    """
    Check whether PR has an associated issue and is merged

    Args:
        pull (dict): pull request object
    Returns:
        bool: whether PR is valid
    """
    
    #return True #changed
    '''if pull["merged_at"] is None:
        return False'''
    if "resolved_issues" not in pull or len(pull["resolved_issues"]) < 1:
        return False
    print(pull["resolved_issues"])
    return True


def is_valid_instance(instance: dict) -> bool:
    """
    Check whether task instance has all required fields for task instance creation

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance is valid
    """
    if instance["patch"] is None or instance["patch"] == "":
        return False
    if instance["problem_statement"] is None or instance["problem_statement"] == "":
        return False
    return True


def has_test_patch(instance: dict) -> bool:
    """
    Check whether task instance has a test suite

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance has a test suite
    """
    if instance["test_patch"] is None or instance["test_patch"].strip() == "":
        return False
    #print(instance["test_patch"])
    return True


def main(pr_file: str, output: str, token: Optional[str] = None):
    """
    Main thread for creating task instances from pull requests

    Args:
        pr_file (str): path to pull request JSONL file
        output (str): output file name
        token (str): GitHub token
    """
    if token is None:
        # Get GitHub token from environment variable if not provided
        token = os.environ.get("GITHUB_TOKEN")

    def load_repo(repo_name):
        # Return repo object for a given repo name
        owner, repo = repo_name.split("/")
        return Repo(owner, repo, token=token)

    repos = dict()
    completed = 0
    with_tests = 0
    total_instances = 0
    all_output = output + ".all"
    seen_prs = set()

    # Continue where we left off if output file already exists
    if os.path.exists(all_output):
        with open(all_output) as f:
            for line in f:
                pr = json.loads(line)
                if "instance_id" not in pr:
                    pr["instance_id"] = (
                        pr["repo"] + "-" + str(pr["pull_number"])
                    ).replace("/", "__")
                instance_id = pr["instance_id"]
                seen_prs.add(instance_id)
                if is_valid_instance(pr):
                    completed += 1
                    if has_test_patch(pr):
                        with_tests += 1
    logger.info(
        f"Will skip {len(seen_prs)} pull requests that have already been inspected"
    )

    # Write to .all file for all PRs
    write_mode_all = "w" if not os.path.exists(all_output) else "a"
    with open(all_output, write_mode_all) as all_output:
        # Write to output file for PRs with test suites
        write_mode = "w" if not os.path.exists(output) else "a"
        with open(output, write_mode) as output:
            for ix, line in enumerate(open(pr_file)):
                total_instances += 1
                pull = json.loads(line)
                if ix % 100 == 0:
                    logger.info(
                        f"[{pull['base']['repo']['full_name']}] (Up to {ix} checked) "
                        f"{completed} valid, {with_tests} with tests."
                    )
                # Construct instance fields
                instance_id = (
                    pull["base"]["repo"]["full_name"] + "-" + str(pull["number"])
                )
                instance_id = instance_id.replace("/", "__")
                if instance_id in seen_prs:
                    seen_prs -= {instance_id}
                    continue
                if not is_valid_pull(pull):
                    # Throw out invalid PRs
                    continue
                # Create task instance
                repo_name = pull["base"]["repo"]["full_name"]
                if repo_name not in repos:
                    repos[repo_name] = load_repo(repo_name)
                repo = repos[repo_name]
                instance = create_instance(repo, pull)
                if is_valid_instance(instance):
                    # If valid, write to .all output file
                    print(
                        json.dumps(instance), end="\n", flush=True, file=all_output
                    )  # write all instances to a separate file
                    completed += 1
                    if has_test_patch(instance):
                        # If has test suite, write to output file
                        print(json.dumps(instance), end="\n", flush=True, file=output)
                        with_tests += 1
    logger.info(
        f"[{', '.join(repos.keys())}] Total instances: {total_instances}, completed: {completed}, with tests: {with_tests}"
    )
    logger.info(
        f"[{', '.join(repos.keys())}] Skipped {len(seen_prs)} pull requests that have already been inspected"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_file", type=str, help="Path to pull request JSONL file")
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument("--token", type=str, help="GitHub token")
    args = parser.parse_args()
    main(**vars(args))
