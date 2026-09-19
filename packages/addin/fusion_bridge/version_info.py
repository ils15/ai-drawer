"""Add-in version metadata.

Reports the add-in version and the git commit it was built from. These helpers
used to live in the module that implemented the removed arbitrary-code-execution
tool; they are pure infrastructure and were extracted when that module was
deleted, so reporting version info no longer requires keeping an execution
module around.
"""

import os

from ..lib import fusionAddInUtils as futil
from ..lib import mcp_server as mcp_server_module

_CACHED_VERSION_INFO = None


def get_addin_dir():
    """Return the directory that contains the add-in package root."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_git_dirs(addin_dir):
    """Return ``(git_dir, common_dir)`` for the add-in's repository.

    Handles both a normal ``.git`` directory and a ``.git`` worktree pointer
    file, and follows ``commondir`` so linked worktrees resolve correctly.
    """
    git_entry = os.path.join(addin_dir, ".git")
    if os.path.isdir(git_entry):
        git_dir = git_entry
    elif os.path.isfile(git_entry):
        with open(git_entry, encoding="utf-8") as handle:
            raw = handle.read().strip()
        if not raw.startswith("gitdir:"):
            raise ValueError(f"Unsupported .git file format at {git_entry}")
        git_dir = raw.split(":", 1)[1].strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.normpath(os.path.join(addin_dir, git_dir))
    else:
        raise FileNotFoundError(f"Missing .git entry at {git_entry}")

    common_dir = git_dir
    commondir_file = os.path.join(git_dir, "commondir")
    if os.path.exists(commondir_file):
        with open(commondir_file, encoding="utf-8") as handle:
            common_dir = handle.read().strip()
        if not os.path.isabs(common_dir):
            common_dir = os.path.normpath(os.path.join(git_dir, common_dir))

    return git_dir, common_dir


def _read_ref(git_dir, common_dir, ref_name):
    """Return the short SHA of *ref_name*, or ``None`` when unavailable."""
    for base_dir in (git_dir, common_dir):
        ref_path = os.path.join(base_dir, ref_name)
        if os.path.exists(ref_path):
            with open(ref_path, encoding="utf-8") as handle:
                return handle.read().strip()[:8]

    packed_refs = os.path.join(common_dir, "packed-refs")
    if os.path.exists(packed_refs):
        with open(packed_refs, encoding="utf-8") as handle:
            for line in handle:
                if line.strip().endswith(ref_name):
                    return line.split()[0][:8]

    return None


def get_version_info(addin_dir):
    """Return a version string such as ``v1.4.1 (ff5f43af)``.

    The git commit suffix is best-effort: a missing or unreadable repository
    degrades gracefully to just the version. The result is cached because the
    values cannot change within a single add-in process.
    """
    global _CACHED_VERSION_INFO
    if _CACHED_VERSION_INFO is not None:
        return _CACHED_VERSION_INFO

    version = mcp_server_module.SERVER_INFO.get("version", "unknown")
    git_commit = None
    try:
        git_dir, common_dir = _resolve_git_dirs(addin_dir)
        head_file = os.path.join(git_dir, "HEAD")
        if os.path.exists(head_file):
            with open(head_file, encoding="utf-8") as handle:
                head = handle.read().strip()
            if head.startswith("ref: "):
                ref_name = head[5:]
                git_commit = _read_ref(git_dir, common_dir, ref_name)
            else:
                git_commit = head[:8]
    except Exception as exc:
        futil.log(f"[version] git commit lookup failed: {exc}")

    _CACHED_VERSION_INFO = f"v{version} ({git_commit})" if git_commit else f"v{version}"
    return _CACHED_VERSION_INFO
