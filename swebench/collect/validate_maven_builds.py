import os
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from tqdm import tqdm  # progress bar!

REPO_URL = "https://github.com/spring-projects/spring-boot.git"
INPUT_FILE = "spring-boot-task-instances.jsonl"
OUTPUT_FILE = "spring-boot-validated-instances.jsonl"
FAIL_FILE = "spring-boot-failed-builds.jsonl"

def run_cmd(cmd, cwd):
    try:
        result = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300
        )
        return result.returncode == 0, result.stdout.decode()
    except subprocess.TimeoutExpired:
        return False, "Timeout"

def apply_patch(patch_text, cwd):
    patch_file = Path(cwd) / "patch.diff"
    patch_file.write_text(patch_text)
    return run_cmd(["git", "apply", "patch.diff"], cwd=cwd)

def validate_instance(instance):
    with TemporaryDirectory() as tmpdir:
        success, out = run_cmd(["git", "clone", REPO_URL, "."], tmpdir)
        if not success:
            return False, "Clone failed"

        success, out = run_cmd(["git", "checkout", instance["base_commit"]], tmpdir)
        if not success:
            return False, "Checkout failed"

        success, out = apply_patch(instance["patch"], tmpdir)
        if not success:
            return False, f"Patch failed: {out}"

        success, out = run_cmd(["mvn", "clean", "install", "-DskipTests"], tmpdir)
        return success, out

def main():
    validated, failed = [], []

    with open(INPUT_FILE, "r") as f:
        instances = [json.loads(line) for line in f]

    for instance in tqdm(instances, desc="Validating PRs"):
        pr_num = instance["pull_number"]
        print(f"\n🔍 Validating PR #{pr_num}...")

        success, log = validate_instance(instance)
        instance["maven_build_passed"] = success
        instance["build_log"] = log[:1000]

        if success:
            print(f"✅ Build passed for PR #{pr_num}")
            validated.append(instance)
        else:
            print(f"❌ Build failed for PR #{pr_num}")
            failed.append(instance)

    # Save passed builds
    with open(OUTPUT_FILE, "w") as f:
        for inst in validated:
            f.write(json.dumps(inst) + "\n")

    # Save failed builds (optional)
    with open(FAIL_FILE, "w") as f:
        for inst in failed:
            f.write(json.dumps(inst) + "\n")

    print(f"\n Validation complete.")
    print(f"Passed: {len(validated)} / {len(instances)}")
    print(f"Output saved to: {OUTPUT_FILE} and {FAIL_FILE}")

if __name__ == "__main__":
    main()

