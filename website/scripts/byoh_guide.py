"""Read-only website projection of the reviewed BYOH guide."""
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

PIN = "562f7e4cbaee6cdf935a17107e9bfce75b9d8d46"
REPO = "https://github.com/openkubes/ok-baremetal-byoh"
CHAPTERS = (
    "01-introduction.md",
    "02-architecture.md",
    "03-infrastructure-requirements.md",
    "04-management-cluster.md",
    "05-host-registration.md",
    "06-cluster-provisioning.md",
    "07-networking.md",
    "08-cluster-operations.md",
    "09-in-place-upgrade.md",
    "10-safety-recovery.md",
    "11-cluster-lifecycle.md",
    "12-validation-limitations.md",
)
DIAGRAMS = (
    "artifact-provenance.svg",
    "byoh-architecture-overview.svg",
    "byoh-host-lifecycle.svg",
    "byoh-host-registration.svg",
    "byoh-lifecycle-safety.svg",
    "byoh-resource-model.svg",
    "host-reuse.svg",
    "infrastructure-independence.svg",
    "infrastructure-readiness.svg",
    "management-bootstrap.svg",
    "networking.svg",
    "recovery.svg",
    "upgrade.svg",
)
ROUTE = "docs/byoh/advanced-guide"
SOURCE_DIR = "docs/advanced-guide"
LINK = re.compile(r"\]\(([^\s()]+)\)")
IMAGE = re.compile(r"!\[([^\]\n]+)\]\((images/[^\s()]+\.svg)\)")


def safe_file(root, relative):
    path = root / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise SystemExit(f"Missing or unsafe BYOH source: {path}")
    return path


def project_markdown(text, repo):
    """Keep guide-local links local; resolve external-to-guide links at the same pin."""
    def rewrite(match):
        target = match.group(1)
        if not target.startswith("../"):
            return match.group(0)
        path, separator, fragment = target.partition("#")
        relative = posixpath.normpath(posixpath.join(SOURCE_DIR, path))
        if relative.startswith("../") or relative == "..":
            raise SystemExit(f"BYOH reference escapes source repository: {target}")
        source = repo / relative
        if not source.exists() or not source.resolve().is_relative_to(repo.resolve()):
            raise SystemExit(f"Missing BYOH reference: {target}")
        kind = "tree" if source.is_dir() else "blob"
        return f"]({REPO}/{kind}/{PIN}/{relative}{separator}{fragment})"
    text = LINK.sub(rewrite, text)
    # Native link fallback also works without JavaScript; shared lightbox enhances it.
    return IMAGE.sub(lambda m: f"[{m.group(0)}]({m.group(2)})", text)


def stage(workspace, staging):
    repo = workspace / "ok-baremetal-byoh"
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        raise SystemExit(f"BYOH checkout must match reviewed revision {PIN}, got {head}")
    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise SystemExit("Refusing modified BYOH source checkout")
    source = repo / SOURCE_DIR
    dest = staging / ROUTE
    (dest / "images").mkdir(parents=True, exist_ok=True)
    for name in ("README.md", *CHAPTERS):
        text = safe_file(source, name).read_text(encoding="utf-8")
        output = "index.md" if name == "README.md" else name
        (dest / output).write_text(project_markdown(text, repo), encoding="utf-8")
    for name in DIAGRAMS:
        relative = "images/" + name
        src = safe_file(source, relative)
        root = ET.parse(src).getroot()
        if root.tag != "{http://www.w3.org/2000/svg}svg" or any(e.tag.rsplit("}", 1)[-1] == "image" for e in root.iter()):
            raise SystemExit(f"Expected native SVG: {src}")
        shutil.copy2(src, dest / relative)
    print(f"Staged BYOH guide from {PIN}: {len(CHAPTERS)} chapters, {len(DIAGRAMS)} SVGs")


def check_output(site):
    guide = site / ROUTE
    for name in ("index.html", *(Path(n).stem + "/index.html" for n in CHAPTERS)):
        page = guide / name
        if not page.is_file():
            raise SystemExit(f"Missing BYOH guide output: {page}")
        html = page.read_text(encoding="utf-8")
        if "BYOH Advanced Guide" not in html:
            raise SystemExit(f"Missing BYOH navigation: {page}")
    for name in DIAGRAMS:
        if not (guide / "images" / name).is_file():
            raise SystemExit(f"Missing BYOH diagram: {name}")
    for page in (site / "docs/index.html", site / "openkubes-byoh-controller/index.html"):
        if "advanced-guide" not in page.read_text(encoding="utf-8"):
            raise SystemExit(f"Missing BYOH guide entry link: {page}")
