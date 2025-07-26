import os
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

REPO_PATH = Path("./spring-boot")
INPUT_FILE = "spring-boot-task-instance.jsonl"
OUTPUT_FILE = "spring-boot-validated-instances-fast.jsonl"
FAIL_FILE = "spring-boot-failed-builds-fast.jsonl"
MAX_LOG_SIZE = 3000
MAX_WORKERS = 1  # Can increase for parallelism later

def run_cmd(cmd, cwd, env=None):
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=6000,
        )
        return result.returncode == 0, result.stdout.decode(errors="replace")
    except subprocess.TimeoutExpired:
        print("Timeout")
        return False, " Timeout"

def prepare_worktree(repo_path, commit, tmpdir):
    worktree_path = Path(tmpdir) / "repo"
    success, log = run_cmd(["git", "worktree", "add", "--detach", str(worktree_path), commit], cwd=repo_path)
    return success, worktree_path, log

def remove_worktree(worktree_path):
    run_cmd(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=REPO_PATH)

def apply_patch(patch_text, cwd):
    patch_file = Path(cwd) / "patch.diff"
    patch_file.write_text(patch_text)
    return run_cmd(["git", "apply", "patch.diff"], cwd=cwd)

def validate_instance(instance):
    pr_num = instance["pull_number"]
    result = instance.copy()

    with TemporaryDirectory() as tmpdir:
        success, worktree_dir, log = prepare_worktree(REPO_PATH, instance["base_commit"], tmpdir)
        if not success:
            result["build_passed"] = False
            result["build_log"] = f" Worktree creation failed:\n{log[:MAX_LOG_SIZE]}"
            result["pr_status"] = f" PR #{pr_num}: Worktree creation failed"
            return result

        try:
            success, out = apply_patch(instance["patch"], worktree_dir)
            if not success:
                result["build_passed"] = False
                result["build_log"] = f"Patch failed:\n{out[:MAX_LOG_SIZE]}"
                result["pr_status"] = f" PR #{pr_num}: Patch failed"
                return result

            gradle_cmd = [
                "./gradlew", "build", "-x", "test",
                "--daemon", "--build-cache"  # ⚠️ NO --offline here!
            ]

            # Use system-wide Gradle cache
            gradle_env = os.environ.copy()

            success, out = run_cmd(gradle_cmd, cwd=worktree_dir, env=gradle_env)
            result["build_passed"] = success
            result["build_log"] = out[:MAX_LOG_SIZE]
            result["pr_status"] = f"{'✅' if success else '❌'} PR #{pr_num}: {'Passed' if success else 'Failed'}"
            return result

        finally:
            remove_worktree(worktree_dir)

def main():
    with open(INPUT_FILE, "r") as f:
        instances = [json.loads(line) for line in f]

    print(f"Starting validation for {len(instances)} PRs using {MAX_WORKERS} thread(s)...\n")

    validated, failed = [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_instance = {executor.submit(validate_instance, inst): inst for inst in instances}
        for future in tqdm(as_completed(future_to_instance), total=len(instances), desc="🔍 Validating PRs"):
            result = future.result()
            print(result["pr_status"])
            if result["build_passed"]:
                validated.append(result)
            else:
                failed.append(result)

    with open(OUTPUT_FILE, "w") as f:
        for inst in validated:
            f.write(json.dumps(inst) + "\n")

    with open(FAIL_FILE, "w") as f:
        for inst in failed:
            f.write(json.dumps(inst) + "\n")

    print(f"\n✅ Validation complete.")
    print(f"Passed: {len(validated)} / {len(instances)}")
    print(f"Saved: {OUTPUT_FILE}, {FAIL_FILE}")

if __name__ == "__main__":
    main()
