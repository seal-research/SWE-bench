import os
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from tqdm import tqdm

REPO_URL = "https://github.com/spring-projects/spring-boot.git"
INPUT_FILE = "spring-boot-task-instance.jsonl"
OUTPUT_FILE = "spring-boot-validated-instances.jsonl"
FAIL_FILE = "spring-boot-failed-builds.jsonl"
MAX_LOG_SIZE = 10000  # Truncate logs to avoid bloating JSONL

if os.name == "nt":
    gradle_cmd = ["gradlew.bat", "build", "-x", "test", "--build-cache", "--daemon"]
else:
    gradle_cmd = ["./gradlew", "build", "-x", "test", "--build-cache", "--daemon"]


def run_cmd(cmd, cwd):
    try:
        result = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=6000
        )
        return result.returncode == 0, result.stdout.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return False, " Timeout"


def apply_patch(patch_text, cwd, name="patch.diff"):
    patch_file = Path(cwd) / name
    patch_file.write_text(patch_text)
    return run_cmd(["git", "apply", name], cwd=cwd)


def extract_submodule_from_patch(patch_text):
    for line in patch_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) > 2:
                path = parts[2].replace("a/", "")
                parts = path.split("/")
                if "src" in parts:
                    idx = parts.index("src")
                    return "/".join(parts[:idx])
                else:
                    return os.path.dirname(path)
    return None


def disable_global_werror(repo_dir):
    """
    Injects code into root `build.gradle` to disable `-Werror` globally.
    """
    gradle_root = Path(repo_dir) / "build.gradle"
    if gradle_root.exists():
        try:
            with open(gradle_root, "a") as f:
                f.write("""

// --- PATCHED BY SCRIPT: Disable global -Werror ---
allprojects {
    tasks.withType(JavaCompile).configureEach {
        options.compilerArgs.removeAll { it == '-Werror' }
    }
}
""")
            print("✅ Patched root build.gradle to remove -Werror globally.")
        except Exception as e:
            print(f"⚠️ Failed to patch root build.gradle: {e}")
    else:
        print(f"⚠️ Root build.gradle not found at {gradle_root}")


def validate_instance(instance):
    result = {
        "instance_id": instance.get("instance_id"),
        "pull_number": instance.get("pull_number"),
        "patch_applied": False,
        "patch_build_passed": False,
        "test_patch_applied": False,
        "test_build_passed": False,
        "patch_build_log": "",
        "test_build_log": "",
    }

    with TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        success, log = run_cmd(["git", "clone", REPO_URL, str(repo_dir)], cwd=tmpdir)
        if not success:
            result["patch_build_log"] = f" Clone failed:\n{log[:MAX_LOG_SIZE]}"
            return result

        print(f"📦 Cloned repo to: {repo_dir}")
        success, log = run_cmd(["git", "checkout", instance["base_commit"]], cwd=str(repo_dir))
        if not success:
            result["patch_build_log"] = f"Checkout failed:\n{log[:MAX_LOG_SIZE]}"
            return result

        disable_global_werror(repo_dir)  # <<< Inject -Werror removal

        success, log = apply_patch(instance["patch"], cwd=str(repo_dir), name="patch.diff")
        if not success:
            result["patch_build_log"] = f" Patch failed:\n{log[:MAX_LOG_SIZE]}"
            return result
        result["patch_applied"] = True

        submodule_path = extract_submodule_from_patch(instance["patch"])
        if not submodule_path:
            result["patch_build_log"] = " Could not determine submodule from patch."
            return result

        gradlew = repo_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
        if not gradlew.exists():
            result["patch_build_log"] = " gradlew not found in repo root."
            return result

        gradle_exec = str(gradlew)
        gradle_module = ":" + submodule_path.replace("/", ":")
        build_cmd = [gradle_exec, gradle_module + ":build", "-x", "test", "--build-cache", "--daemon"]

        print(f"⚙️  Running build: {build_cmd}")
        success, log = run_cmd(build_cmd, cwd=repo_dir)
        result["patch_build_passed"] = success
        result["patch_build_log"] = log[:MAX_LOG_SIZE]

        if not success:
            return result

        # If test patch is available
        if "test_patch" in instance and instance["test_patch"]:
            success, log = apply_patch(instance["test_patch"], cwd=str(repo_dir), name="test_patch.diff")
            if not success:
                result["test_build_log"] = f"Test patch failed:\n{log[:MAX_LOG_SIZE]}"
                return result
            result["test_patch_applied"] = True

            test_cmd = [gradle_exec, gradle_module + ":test", "--build-cache", "--daemon"]
            success, log = run_cmd(test_cmd, cwd=repo_dir)
            result["test_build_passed"] = success
            result["test_build_log"] = log[:MAX_LOG_SIZE]

    return result


def main():
    validated, failed = [],[]

    with open(INPUT_FILE, "r") as f:
        instances = [json.loads(line) for line in f]

    for instance in tqdm(instances, desc=" Validating PRs"):
        pr_num = instance.get("pull_number", "???")
        print(f"\n🔍 Validating PR #{pr_num}")

        result = validate_instance(instance)
        instance.update(result)

        if result["patch_build_passed"]:
            print(f"✅ Patch build passed for PR #{pr_num}")
            validated.append(instance)
        else:
            print(f"❌ Patch build failed for PR #{pr_num}")
            failed.append(instance)

    with open(OUTPUT_FILE, "w") as f:
        for inst in validated:
            f.write(json.dumps(inst) + "\n")

    with open(FAIL_FILE, "w") as f:
        for inst in failed:
            f.write(json.dumps(inst) + "\n")

    print(f"\n Validation complete: {len(validated)} passed / {len(instances)} total")
    print(f" Output: {OUTPUT_FILE}")
    print(f" Failures: {FAIL_FILE}")


if __name__ == "__main__":
    main()
