import subprocess
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_URL = "https://github.com/spring-projects/spring-boot.git"
REPO_DIR = Path("spring-boot")

def run_cmd(cmd, cwd=None, check=True):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0 and check:
        print(f"Command failed with exit code {result.returncode}")
        print(result.stdout)
        print(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result

def clone_or_update_repo():
    if not REPO_DIR.exists():
        run_cmd(["git", "clone", REPO_URL], check=True)
    else:
        run_cmd(["git", "fetch", "origin"], cwd=REPO_DIR)

def apply_patch_and_build(pr_data):
    instance_id = pr_data["instance_id"]
    pr_number = pr_data["pull_number"]
    patch = pr_data["patch"]
    base_commit = pr_data["base_commit"]
    print(f"\n[+] Validating PR #{pr_number} - {instance_id}\n")

    # Reset repo and checkout base commit
    run_cmd(["git", "reset", "--hard"], cwd=REPO_DIR)
    run_cmd(["git", "checkout", base_commit], cwd=REPO_DIR)

    # Apply the patch
    patch_path = Path(f"{instance_id}.patch")
    patch_path.write_text(patch)
    try:
        run_cmd(["git", "apply", "--whitespace=fix", str(patch_path)], cwd=REPO_DIR)
    except subprocess.CalledProcessError:
        print(f"❌ Failed to apply patch for PR #{pr_number}")
        return False

    # Detect Gradle or Maven
    if (REPO_DIR / "gradlew").exists():
        build_cmd = ["./gradlew", "build", "--no-daemon", "--continue"]
    elif (REPO_DIR / "pom.xml").exists():
        build_cmd = ["mvn", "clean", "install", "-DskipTests=false"]
    else:
        raise RuntimeError("No recognized build tool found (Gradle or Maven).")

    # Run the build
    try:
        run_cmd(build_cmd, cwd=REPO_DIR)
        print(f"✅ Build successful for PR #{pr_number}")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Build failed for PR #{pr_number}")
        return False

def main():
    input_file = "spring-boot-task-instance.jsonl"
    output_file = "spring-boot-validated-instance.jsonl"
    failed_file = "spring-boot-failed-build.jsonl"

    clone_or_update_repo()

    with open(input_file, "r") as infile, \
         open(output_file, "w") as passed_out, \
         open(failed_file, "w") as failed_out:

        for line in infile:
            try:
                pr_data = json.loads(line)
                if apply_patch_and_build(pr_data):
                    passed_out.write(json.dumps(pr_data) + "\n")
                else:
                    failed_out.write(json.dumps(pr_data) + "\n")
            except Exception as e:
                print(f"❌ Error validating PR: {e}")
                failed_out.write(line)

if __name__ == "__main__":
    main()
