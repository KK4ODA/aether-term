"""
updater.py — Git-based auto-updater for Aether Term.

Fetches from origin, compares HEAD with the remote tracking branch,
and (optionally) pulls + signals for a restart.
"""

import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class CommitSummary:
    hash: str
    author: str
    date: str
    subject: str


@dataclass
class UpdateCheckResult:
    update_available: bool = False
    current_hash: str = ""
    remote_hash: str = ""
    commits: list[CommitSummary] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class UpdateApplyResult:
    success: bool = False
    old_hash: str = ""
    new_hash: str = ""
    error: Optional[str] = None


class GitError(Exception):
    """Raised when a git command fails."""


# ── Updater ─────────────────────────────────────────────────────────────────

class Updater(QObject):
    """Check for and apply updates via git pull.

    Emits Qt signals so the GUI can react on the main thread.
    """

    update_available = pyqtSignal(object)   # UpdateCheckResult
    update_failed = pyqtSignal(str)         # error message

    def __init__(self, config, repo_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._repo = repo_dir or _REPO_ROOT
        self._config = config
        self._last_check: Optional[UpdateCheckResult] = None

    # ── public properties ───────────────────────────────────────────────

    @property
    def last_check(self) -> Optional[UpdateCheckResult]:
        return self._last_check

    # ── git helpers ─────────────────────────────────────────────────────

    def _run_git(self, *args: str) -> str:
        """Run a git command and return stdout.  Raises GitError on failure."""
        cmd = ["git"] + list(args)
        try:
            r = subprocess.run(
                cmd,
                cwd=self._repo,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            raise GitError("git is not installed or not on PATH")
        except subprocess.TimeoutExpired:
            raise GitError(f"git command timed out: {' '.join(cmd)}")
        if r.returncode != 0:
            raise GitError(r.stderr.strip() or f"git exited with code {r.returncode}")
        return r.stdout.strip()

    def _is_git_repo(self) -> bool:
        if not (self._repo / ".git").exists():
            return False
        try:
            self._run_git("status", "--porcelain")
            return True
        except GitError:
            return False

    def _is_dirty(self) -> bool:
        out = self._run_git("status", "--porcelain")
        return len(out) > 0

    def _parse_log(self, range_spec: str) -> list[CommitSummary]:
        try:
            raw = self._run_git("log", "--format=%h|%an|%ai|%s", range_spec)
        except GitError:
            return []
        commits: list[CommitSummary] = []
        for line in raw.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append(CommitSummary(*parts))
        return commits

    # ── check ───────────────────────────────────────────────────────────

    def check_for_updates(self) -> UpdateCheckResult:
        """Fetch from origin and compare HEAD with the remote branch."""
        result = UpdateCheckResult()
        branch = self._config.get("update_branch", "master")

        try:
            if not self._is_git_repo():
                result.error = "Not a git repository — updates unavailable"
                self.update_failed.emit(result.error)
                self._last_check = result
                return result

            self._run_git("fetch", "origin", branch)

            result.current_hash = self._run_git("rev-parse", "--short", "HEAD")
            result.remote_hash = self._run_git("rev-parse", "--short", f"origin/{branch}")

            if result.current_hash != result.remote_hash:
                result.update_available = True
                result.commits = self._parse_log(f"HEAD..origin/{branch}")
                self.update_available.emit(result)
                log.info(
                    "Update available: %d new commit(s)", len(result.commits),
                )
            else:
                log.info("Software is up to date (%s)", result.current_hash)

        except GitError as e:
            result.error = str(e)
            self.update_failed.emit(result.error)
            log.warning("Update check failed: %s", e)
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            self.update_failed.emit(result.error)
            log.error("Update check error", exc_info=True)

        self._last_check = result
        return result

    # ── apply ───────────────────────────────────────────────────────────

    def apply_update(self) -> UpdateApplyResult:
        """Pull the latest commits.  Returns result — never raises."""
        result = UpdateApplyResult()
        branch = self._config.get("update_branch", "main")

        try:
            # Stash any local changes so they don't block the pull
            stashed = False
            if self._is_dirty():
                try:
                    self._run_git("stash", "push", "-m", "auto-update stash")
                    stashed = True
                    log.info("Stashed local changes before update")
                except GitError:
                    pass  # stash failed, try pull anyway

            result.old_hash = self._run_git("rev-parse", "--short", "HEAD")
            self._run_git("pull", "--ff-only", "origin", branch)
            result.new_hash = self._run_git("rev-parse", "--short", "HEAD")
            result.success = True
            log.info("Updated %s → %s", result.old_hash, result.new_hash)

            # Restore stashed changes
            if stashed:
                try:
                    self._run_git("stash", "pop")
                    log.info("Restored stashed local changes")
                except GitError:
                    log.warning("Could not restore stashed changes (may have conflicts)")

        except GitError as e:
            result.error = str(e)
            log.error("Update failed: %s", e)
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            log.error("Update error", exc_info=True)

        return result

    # ── async ───────────────────────────────────────────────────────────

    def check_once_async(self):
        """Run a single update check on a background thread."""
        t = threading.Thread(
            target=self.check_for_updates,
            name="UpdateCheck",
            daemon=True,
        )
        t.start()


def get_git_hash() -> Optional[str]:
    """Return the short git commit hash, or None if unavailable."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None
