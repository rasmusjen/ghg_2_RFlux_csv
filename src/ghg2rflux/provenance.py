"""File hashing and git metadata for the reproducibility panel.

Transplanted verbatim from GHG2RFLUX.py:171-234. Every git call degrades to
``'N/A'`` independently, so running outside a checkout still produces a report.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess


def compute_file_hash(file_path: str) -> str:
    """SHA256 of a file, or ``'N/A'`` when it does not exist."""
    if not os.path.isfile(file_path):
        return "N/A"

    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def normalize_remote_url(remote_url: str | None) -> str:
    """Rewrite ``git@host:path.git`` as ``https://host/path``."""
    if not remote_url:
        return "N/A"

    url = remote_url.strip()
    if url.startswith("git@") and ":" in url:
        host_path = url[4:]
        host, path = host_path.split(":", 1)
        url = f"https://{host}/{path}"

    if url.endswith(".git"):
        url = url[:-4]

    return url


def get_git_metadata(path: str) -> dict[str, str]:
    """Branch, hashes and links for the checkout containing ``path``."""

    def run_git(args: list[str]) -> str:
        return subprocess.check_output(["git", *args], cwd=path, text=True).strip()

    metadata = {
        "short_hash": "N/A",
        "full_hash": "N/A",
        "branch": "N/A",
        "remote_url": "N/A",
        "commit_url": "N/A",
    }

    # Each probe degrades independently: no checkout, or no git on PATH, still
    # yields a report with "N/A" rather than failing the run.
    with contextlib.suppress(Exception):
        metadata["short_hash"] = run_git(["rev-parse", "--short", "HEAD"])

    with contextlib.suppress(Exception):
        metadata["full_hash"] = run_git(["rev-parse", "HEAD"])

    with contextlib.suppress(Exception):
        metadata["branch"] = run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    try:
        remote_raw = run_git(["config", "--get", "remote.origin.url"])
        remote_https = normalize_remote_url(remote_raw)
        metadata["remote_url"] = remote_https
        if metadata["full_hash"] != "N/A" and remote_https != "N/A":
            metadata["commit_url"] = f"{remote_https}/commit/{metadata['full_hash']}"
    except Exception:
        pass

    return metadata


def compute_tree_hash(directory: str, suffix: str = ".py") -> str:
    """Stable SHA256 over every ``suffix`` file in ``directory``.

    The original hashed the single script file. Now that the code is a package,
    hashing one module would silently under-report what produced a run, so the
    whole package is hashed instead.
    """
    if not os.path.isdir(directory):
        return "N/A"

    digest = hashlib.sha256()
    for current, subdirs, filenames in os.walk(directory):
        subdirs[:] = sorted(d for d in subdirs if d != "__pycache__")
        for name in sorted(filenames):
            if not name.endswith(suffix):
                continue
            path = os.path.join(current, name)
            digest.update(os.path.relpath(path, directory).replace("\\", "/").encode("utf-8"))
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    digest.update(chunk)
    return digest.hexdigest()
