import os
import re
import requests
from dotenv import load_dotenv
from git import Repo, GitCommandError

# ==========================================================
# 1️⃣ Load environment variables
# ==========================================================
load_dotenv()
GITLAB_URL = os.getenv("GITLAB_URL")  # e.g. https://gitlab.com/api/v4
PROJECT_ID = os.getenv("GITLAB_PROJECT_ID")  # numeric project ID
PRIVATE_TOKEN = os.getenv("GITLAB_TOKEN")  # GitLab personal access token
SOURCE_BRANCH = os.getenv("SOURCE_BRANCH", "develop")  # base branch to start from
PATCH_BRANCH = os.getenv("PATCH_BRANCH", "auto-vuln-fix")

HEADERS = {"PRIVATE-TOKEN": PRIVATE_TOKEN}

# ==========================================================
# 2️⃣ Helper functions
# ==========================================================
def normalize_image_name(image):
    """Normalize and clean image names."""
    if not image:
        return None
    image = image.strip().lower()
    if image.endswith(".tar") or "input" in image or "image.tar" in image:
        return None
    image = image.replace("docker.io/", "").replace("public.ecr.aws/", "")
    return image.strip()

def should_update_image(dockerfile_image, vuln_image, vuln_record=None):
    """Compare Dockerfile base image vs vulnerability image."""
    dockerfile_image = normalize_image_name(dockerfile_image)
    vuln_image = normalize_image_name(vuln_image)

    if not vuln_image or vuln_image.endswith(".tar") or "input" in (vuln_image or ""):
        print(f"[INFO] Vulnerability image is local ({vuln_image}); mapping to Dockerfile image.")
        vuln_image = dockerfile_image

    print(f"[DEBUG] Comparing: Dockerfile image={dockerfile_image}, Vulnerability image={vuln_image}")

    if not dockerfile_image or not vuln_image:
        return False

    df_base = dockerfile_image.split(":")[0].split("/")[-1]
    vuln_base = vuln_image.split(":")[0].split("/")[-1]

    if df_base == vuln_base:
        print("[MATCH] Vulnerability applies to Dockerfile base image.")
        return True

    # Fallback for OS-level packages
    if vuln_record:
        pkg_name = vuln_record.get("package", {}).get("name", "")
        if pkg_name in ("glibc", "openssl", "expat", "coreutils", "python3", "pip"):
            print(f"[INFO] Falling back to OS-level vulnerability ({pkg_name}).")
            return True

    return False

def extract_base_image(dockerfile_path):
    """Extract the FROM image from a Dockerfile."""
    with open(dockerfile_path, "r") as f:
        for line in f:
            if line.strip().startswith("FROM "):
                return line.split()[1]
    return None

def apply_patch_to_dockerfile(dockerfile_path, patches):
    """Append patch RUN commands to Dockerfile."""
    print("[INFO] Applying patch commands to Dockerfile...")
    with open(dockerfile_path, "a") as f:
        f.write("\n# --- Auto Patch Added ---\n")
        for patch in patches:
            f.write(f"RUN {patch}\n")
        f.write("# --- End Auto Patch ---\n")

def commit_and_push_from_branch(repo_path, source_branch, patch_branch, message):
    """Create new branch from source, apply commit, and push."""
    repo = Repo(repo_path)
    origin = repo.remote(name="origin")

    # Checkout source branch and pull latest
    print(f"[GIT] Checking out source branch '{source_branch}'...")
    repo.git.checkout(source_branch)
    origin.pull(source_branch)

    # Create patch branch
    try:
        repo.git.checkout("-b", patch_branch)
        print(f"[GIT] Created new branch '{patch_branch}' from '{source_branch}'.")
    except GitCommandError:
        print(f"[GIT] Branch '{patch_branch}' exists. Checking it out.")
        repo.git.checkout(patch_branch)

    # Add and commit Dockerfile changes
    repo.git.add("Dockerfile")
    repo.index.commit(message)

    # Push new branch
    origin.push(patch_branch)
    print(f"[GIT] Changes pushed to remote branch '{patch_branch}'.")

# ==========================================================
# 3️⃣ Fetch vulnerabilities from GitLab
# ==========================================================
def get_container_vulnerabilities():
    url = f"{GITLAB_URL}/projects/{PROJECT_ID}/vulnerabilities"
    vulns = []
    page = 1

    while True:
        resp = requests.get(url, headers=HEADERS, params={"page": page, "per_page": 100}, verify=False)
        if resp.status_code != 200:
            print(f"[ERROR] GitLab API returned {resp.status_code}")
            break
        data = resp.json()
        if not data:
            break
        vulns.extend(data)
        page += 1

    print(f"[INFO] Retrieved {len(vulns)} vulnerabilities.")
    return vulns

# ==========================================================
# 4️⃣ Main logic
# ==========================================================
def main():
    dockerfile_path = "Dockerfile"
    repo_path = os.getcwd()
    dockerfile_image = extract_base_image(dockerfile_path)
    if not dockerfile_image:
        print("[ERROR] Dockerfile base image not found!")
        return

    vulns = get_container_vulnerabilities()
    if not vulns:
        print("[INFO] No vulnerabilities found.")
        return

    patches_to_apply = []

    for vuln in vulns:
        location = vuln.get("location", {})
        vuln_image = location.get("image", "")
        if should_update_image(dockerfile_image, vuln_image, vuln_record=vuln):
            print(f"[PATCH] Detected vulnerability for {dockerfile_image}")
            patches_to_apply.extend([
                "rm -f /etc/dnf/vars/releasever || true",
                "dnf -y update --refresh",
                "dnf -y clean all",
                "python -m pip install --upgrade pip setuptools wheel"
            ])
            break

    if not patches_to_apply:
        print("[INFO] No matching vulnerabilities for base image.")
        return

    apply_patch_to_dockerfile(dockerfile_path, patches_to_apply)
    commit_and_push_from_branch(repo_path, SOURCE_BRANCH, PATCH_BRANCH, "Auto patch for container vulnerabilities")

if __name__ == "__main__":
    main()
