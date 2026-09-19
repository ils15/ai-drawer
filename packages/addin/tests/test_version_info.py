"""Tests for :mod:`fusion_bridge.version_info`.

This module was extracted from the deleted arbitrary-code-execution tool: the
version reporting is pure filesystem work and must not need an execution module
to stay alive.  The git-lookup has to degrade gracefully, because the add-in
also runs from unzipped copies that have no ``.git`` entry at all.
"""

import os
import tempfile
import unittest
from unittest import mock

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)

from fusion_bridge import version_info


class _Base(unittest.TestCase):
    def setUp(self):
        # get_version_info caches for the lifetime of the process.
        version_info._CACHED_VERSION_INFO = None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addin_dir = self.tmp.name

    def write(self, *parts, content=""):
        path = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def dir(self, *parts):
        """Create (if needed) and return a directory inside the temp root."""
        path = os.path.join(self.tmp.name, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def git_dir(self):
        return self.dir(".git")


class ResolveGitDirsTests(_Base):
    def test_plain_git_directory(self):
        git_dir = self.git_dir
        self.write(".git", "HEAD", content="ref: refs/heads/main\n")
        self.assertEqual(
            version_info._resolve_git_dirs(self.addin_dir),
            (git_dir, git_dir),
        )

    def test_missing_git_entry_raises(self):
        with self.assertRaises(FileNotFoundError):
            version_info._resolve_git_dirs(self.addin_dir)

    def test_worktree_pointer_file_resolves_absolute_target(self):
        other = os.path.join(self.tmp.name, "elsewhere.git")
        os.makedirs(other)
        self.write(".git", content=f"gitdir: {other}\n")
        self.assertEqual(version_info._resolve_git_dirs(self.addin_dir), (other, other))

    def test_worktree_pointer_file_resolves_relative_target(self):
        self.write(".git", content="gitdir: elsewhere.git\n")
        expected = os.path.normpath(os.path.join(self.addin_dir, "elsewhere.git"))
        self.assertEqual(version_info._resolve_git_dirs(self.addin_dir), (expected, expected))

    def test_unsupported_pointer_file_format_raises(self):
        self.write(".git", content="not a gitdir pointer\n")
        with self.assertRaises(ValueError):
            version_info._resolve_git_dirs(self.addin_dir)

    def test_commondir_file_is_followed(self):
        git_dir = self.git_dir
        self.write(".git", "HEAD", content="ref: refs/heads/main\n")
        common = os.path.join(self.tmp.name, "common.git")
        os.makedirs(common)
        self.write(".git", "commondir", content=common + "\n")
        self.assertEqual(
            version_info._resolve_git_dirs(self.addin_dir),
            (git_dir, common),
        )

    def test_relative_commondir_is_made_absolute(self):
        git_dir = self.git_dir
        self.write(".git", "HEAD", content="ref: refs/heads/main\n")
        self.write(".git", "commondir", content="common.git\n")
        expected = os.path.normpath(os.path.join(git_dir, "common.git"))
        self.assertEqual(
            version_info._resolve_git_dirs(self.addin_dir),
            (git_dir, expected),
        )


class ReadRefTests(_Base):
    def test_ref_file_in_git_dir(self):
        git_dir = self.git_dir
        self.write(".git", "refs", "heads", "main", content="0123456789abcdef\n")
        self.assertEqual(version_info._read_ref(git_dir, git_dir, "refs/heads/main"), "01234567")

    def test_packed_refs_fallback(self):
        git_dir = self.git_dir
        self.write(".git", "packed-refs", content="abcdef0123456789 refs/heads/main\n")
        self.assertEqual(version_info._read_ref(git_dir, git_dir, "refs/heads/main"), "abcdef01")

    def test_missing_ref_returns_none(self):
        git_dir = self.git_dir
        self.assertIsNone(version_info._read_ref(git_dir, git_dir, "refs/heads/nope"))

    def test_common_dir_is_searched_after_git_dir(self):
        git_dir = self.git_dir
        common = self.dir("common.git")
        self.write("common.git", "refs", "heads", "main", content="fedcba9876543210\n")
        self.assertEqual(version_info._read_ref(git_dir, common, "refs/heads/main"), "fedcba98")


class GetVersionInfoTests(_Base):
    def setUp(self):
        super().setUp()
        server_info_patcher = mock.patch.object(
            version_info.mcp_server_module, "SERVER_INFO", {"name": "t", "version": "1.2.3"}
        )
        server_info_patcher.start()
        self.addCleanup(server_info_patcher.stop)

    def test_symbolic_ref_head_reports_short_commit(self):
        self.write(".git", "HEAD", content="ref: refs/heads/main\n")
        self.write(".git", "refs", "heads", "main", content="0123456789abcdef\n")
        self.assertEqual(version_info.get_version_info(self.addin_dir), "v1.2.3 (01234567)")

    def test_detached_head_reports_short_commit(self):
        self.write(".git", "HEAD", content="abcdef0123456789\n")
        self.assertEqual(version_info.get_version_info(self.addin_dir), "v1.2.3 (abcdef01)")

    def test_missing_repository_degrades_to_plain_version(self):
        # No .git entry at all: still a usable version string, plus a log line.
        with mock.patch.object(version_info.futil, "log") as log:
            self.assertEqual(version_info.get_version_info(self.addin_dir), "v1.2.3")
        log.assert_called_once()
        self.assertIn("git commit lookup failed", log.call_args[0][0])

    def test_malformed_repository_also_degrades_gracefully(self):
        self.write(".git", content="garbage\n")
        self.assertEqual(version_info.get_version_info(self.addin_dir), "v1.2.3")

    def test_unreadable_ref_yields_plain_version(self):
        self.write(".git", "HEAD", content="ref: refs/heads/main\n")
        self.assertEqual(version_info.get_version_info(self.addin_dir), "v1.2.3")

    def test_result_is_cached_for_the_process(self):
        self.write(".git", "HEAD", content="abcdef0123456789\n")
        first = version_info.get_version_info(self.addin_dir)
        # A repository that disappears afterwards must not change the answer.
        self.write(".git", "HEAD", content="ref: refs/heads/gone\n")
        self.assertEqual(version_info.get_version_info(self.addin_dir), first)

    def test_get_addin_dir_points_at_the_package_root(self):
        self.assertEqual(
            os.path.basename(version_info.get_addin_dir()),
            os.path.basename(os.path.dirname(os.path.dirname(version_info.__file__))),
        )


if __name__ == "__main__":
    unittest.main()
