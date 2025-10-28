import os
import re
import tempfile
import requests
import semver
import gitlab
from git import Repo
from urllib.parse import urlparse

# ========== CONFIG ==========
GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
TARGET_BRANCH = "main"
NEW_BRANCH = "auto/container-vuln-patch"
COMMIT_MSG = "fix: auto-patch container image vulnerabilities"
# ============================

gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)

def parse_project_from_url(url):
    """
    Extract project path from GitLab vulnerability report URL.
    Example: https://gitlab.com/mygroup/myrepo/-/security/vulnerabilities
    """
    parts = urlparse(url).path.strip("/").split("/")
    if "-/security" in url:
        parts = parts[:parts.index("-")]
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def get_vulnerabilities(project_path):
    project = gl.projects.get(project_path)
    vulns = project.vulnerabilities.list(all=True)
    return vulns


def is_container_vuln(vuln):
    """
    Detect if a vulnerability is from container scanning.
    """
    try:
        return vuln.report_type == "container_scanning"
    except AttributeError:
        return False


def get_latest_patch_tag(image_name, tag):
    """
    Try fetching latest patch version from Docker Hub.
    """
    if "/" not in image_name:
        namespace = "library"
        repo = image_name
    else:
        namespace, repo = image_name.split("/", 1)

    url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/?page_size=100"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        tags = [t["name"] for t in resp.json().get("results", [])]
    except Exception as e:
        print(f"⚠️ Cannot fetch tags for {image_name}: {e}")
        return None

    match = re.match(r"(\d+)\.(\d+)", tag)
    if not match:
        return None
    major, minor = match.groups()
    pattern = re.compile(fr"^{major}\.{minor}\.\d+")
    candidates = [t for t in tags if pattern.match(t)]
    if not candidates:
        return None

    try:
        latest = max(candidates, key=lambda v: semver.VersionInfo.parse(v))
        if latest != tag:
            return latest
    except Exception:
        pass
    return None


def inject_patch_step(dockerfile_path):
    """
    Inject a dnf/apt patch line if not already present.
    """
    with open(dockerfile_path, "r") as f:
        lines = f.readlines()
    if any("dnf" in l or "apt-get" in l for l in lines):
        return False

    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if line.strip().startswith("FROM") and not inserted:
            if "amazonlinux" in line:
                new_lines.append("RUN dnf -y update && dnf clean all\n")
            elif "debian" in line or "ubuntu" in line or "python" in line:
                new_lines.append("RUN apt-get update && apt-get -y upgrade && apt-get clean\n")
            inserted = True

    with open(dockerfile_path, "w") as f:
        f.writelines(new_lines)
    print(f"🧩 Added OS patch step to {dockerfile_path}")
    return True


def update_dockerfile(df_path, image_name, current_tag):
    changed = False
    new_lines = []
    with open(df_path, "r") as f:
        lines = f.readlines()
    for line in lines:
        match = re.match(r"FROM\s+([^\s:]+):([\w.\-]+)", line.strip())
        if match:
            base, tag = match.groups()
            if image_name in base and tag == current_tag:
                new_tag = get_latest_patch_tag(base, tag)
                if new_tag:
                    print(f"🛠 Updating {base}:{tag} → {new_tag}")
                    line = f"FROM {base}:{new_tag}\n"
                    changed = True
        new_lines.append(line)
    if changed:
        with open(df_path, "w") as f:
            f.writelines(new_lines)
    return changed


def main():
    vuln_url = input("Enter GitLab Vulnerability URL: ").strip()
    project_path = parse_project_from_url(vuln_url)
    if not project_path:
        print("❌ Could not parse project path from URL.")
        return

    project = gl.projects.get(project_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        print("📥 Cloning repository...")
        repo = Repo.clone_from(project.http_url_to_repo, tmpdir)
        repo.git.checkout(TARGET_BRANCH)

        dockerfiles = []
        for root, _, files in os.walk(tmpdir):
            for f in files:
                if f.lower().startswith("dockerfile"):
                    dockerfiles.append(os.path.join(root, f))

        vulns = get_vulnerabilities(project_path)
        container_vulns = [v for v in vulns if is_container_vuln(v)]
        print(f"🔎 Found {len(container_vulns)} container vulnerabilities")

        any_change = False
        for vuln in container_vulns:
            loc = getattr(vuln, "location", {}) or {}
            image = loc.get("image")
            if not image or ":" not in image:
                continue
            base, tag = image.split(":", 1)
            for df in dockerfiles:
                updated = update_dockerfile(df, base, tag)
                injected = inject_patch_step(df)
                if updated or injected:
                    any_change = True
                    repo.git.add(df)

        if not any_change:
            print("✅ No changes required, all images up to date or patched.")
            return

        repo.git.checkout("-b", NEW_BRANCH)
        repo.index.commit(COMMIT_MSG)
        origin = repo.remote(name="origin")
        origin.push(refspec=f"{NEW_BRANCH}:{NEW_BRANCH}")

        mr = project.mergerequests.create({
            "source_branch": NEW_BRANCH,
            "target_branch": TARGET_BRANCH,
            "title": "Auto Patch: Container Vulnerability Fix",
        })
        print(f"✅ Merge Request Created: {mr.web_url}")


if __name__ == "__main__":
    if not GITLAB_TOKEN:
        print("❌ Please set GITLAB_TOKEN environment variable.")
    else:
        main()
        
