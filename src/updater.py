"""
updater.py — Auto-updater for Aether Term.

Two modes, picked by how Aether Term is installed:

* **git** (a clone, e.g. from ``setup_term.bat``): fetches from origin,
  compares HEAD with the remote tracking branch, and pulls + restarts.
* **release** (the installer or the portable zip — no ``.git``): asks the
  GitHub Releases API for the latest release and, when it is newer than the
  running version, offers its download page.
"""

import json
import logging
import re
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

GITHUB_REPO = "KK4ODA/aether-term"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


def parse_version(text: str) -> tuple:
    """``"v1.10.2"`` → ``(1, 10, 2)``; anything unparsable → ``()``."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return ()
    return tuple(int(g or 0) for g in m.groups())


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_version(remote), parse_version(local)
    return bool(r) and bool(l) and r > l


def _ssl_context() -> ssl.SSLContext:
    # A frozen build may not find the system's certificates; certifi's
    # bundle is shipped with it (requirements.txt).
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


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
    # release mode only
    mode: str = "git"
    release_tag: str = ""
    release_name: str = ""
    release_notes: str = ""
    release_url: str = ""

    @property
    def label(self) -> str:
        """Short text for the status-bar indicator."""
        if self.mode == "release":
            return f"UPDATE {self.release_tag}"
        return f"UPDATE ({len(self.commits)})"


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
    """Check for and apply updates (git pull, or a newer GitHub release).

    Emits Qt signals so the GUI can react on the main thread.
    """

    update_available = pyqtSignal(object)   # UpdateCheckResult
    update_failed = pyqtSignal(str)         # error message

    def __init__(self, config, repo_dir: Optional[Path] = None, parent=None,
                 current_version: Optional[str] = None,
                 releases_api: str = RELEASES_API):
        super().__init__(parent)
        self._repo = repo_dir or _REPO_ROOT
        self._config = config
        self._last_check: Optional[UpdateCheckResult] = None
        if current_version is None:
            from config import APP_VERSION
            current_version = APP_VERSION
        self._current_version = current_version
        self._releases_api = releases_api
        self._mode: Optional[str] = None

    @property
    def mode(self) -> str:
        """``"git"`` for a clone, ``"release"`` for an installed build."""
        if self._mode is None:
            self._mode = "git" if self._is_git_repo() else "release"
        return self._mode

    @property
    def is_git(self) -> bool:
        return self.mode == "git"

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
        """Check for a newer version, by git or by GitHub release."""
        if not self.is_git:
            return self._check_release()

        result = UpdateCheckResult()
        branch = self._config.get("update_branch", "main")

        try:
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

    def _check_release(self) -> UpdateCheckResult:
        """Compare the running version with the latest GitHub release."""
        result = UpdateCheckResult(mode="release",
                                   current_hash=self._current_version)
        try:
            req = urllib.request.Request(self._releases_api, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "AetherTerm-Updater",
            })
            with urllib.request.urlopen(req, timeout=15,
                                        context=_ssl_context()) as resp:
                rel = json.loads(resp.read().decode("utf-8"))
            tag = str(rel.get("tag_name") or "")
            result.release_tag = tag
            result.remote_hash = tag
            result.release_name = str(rel.get("name") or tag)
            result.release_notes = str(rel.get("body") or "")
            result.release_url = str(rel.get("html_url") or RELEASES_PAGE)
            if is_newer(tag, self._current_version):
                result.update_available = True
                self.update_available.emit(result)
                log.info("Release %s available (running %s)", tag, self._current_version)
            else:
                log.info("Up to date (running %s, latest release %s)",
                         self._current_version, tag or "none")
        except urllib.error.HTTPError as e:
            # 404: no release published yet
            result.error = None if e.code == 404 else f"GitHub answered HTTP {e.code}"
        except Exception as e:
            result.error = f"Release check failed: {e}"
        if result.error:
            self.update_failed.emit(result.error)
            log.warning(result.error)
        self._last_check = result
        return result

    # ── apply ───────────────────────────────────────────────────────────

    def apply_update(self) -> UpdateApplyResult:
        """Pull the latest commits.  Returns result — never raises.

        Git mode only: an installed build is updated by running the new
        installer, which the update dialog links to.
        """
        result = UpdateApplyResult()
        if not self.is_git:
            result.error = "Installed build — download the new release instead"
            return result
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
