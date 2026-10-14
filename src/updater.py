"""
updater.py — Auto-updater for Aether Term.

Two modes, picked by how Aether Term is installed:

* **git** (a clone, e.g. from ``setup_term.bat``): fetches from origin,
  compares HEAD with the remote tracking branch, and pulls + restarts.
* **release** (the installer or the portable zip — no ``.git``): asks the
  GitHub Releases API for the latest release and, when it is newer than the
  running version, offers it.  An installed build can download the release's
  setup program, check it against the digest GitHub publishes, and run it;
  a portable build is pointed at the download page.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

GITHUB_REPO = "KK4ODA/aether-term"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

# The Inno Setup program attached to each release (installer.iss)
_INSTALLER_ASSET_RE = re.compile(r"^Aether_Term_Setup_.*\.exe$", re.IGNORECASE)

# Arguments for an unattended upgrade: progress window only, no questions;
# the installer's [Run] entry starts the new version when it is done.
INSTALLER_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


def is_installed_build() -> bool:
    """True when running from the installer's copy (not a clone or portable zip).

    Inno Setup leaves its uninstaller next to the executable.
    """
    if not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).resolve().parent / "unins000.exe").exists()


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
    installer_url: str = ""      # the setup program attached to the release
    installer_name: str = ""
    installer_size: int = 0
    installer_sha256: str = ""   # from GitHub's asset digest, when published

    @property
    def version_key(self) -> str:
        """What "Skip this version" remembers."""
        return self.release_tag if self.mode == "release" else self.remote_hash

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
    check_finished = pyqtSignal(object)     # UpdateCheckResult, after every check

    def __init__(self, config, repo_dir: Optional[Path] = None, parent=None,
                 current_version: Optional[str] = None,
                 releases_api: str = RELEASES_API):
        super().__init__(parent)
        self._repo = repo_dir or _REPO_ROOT
        self._config = config
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
            raw = self._run_git("log", "--format=%h|%an|%s", range_spec)
        except GitError:
            return []
        commits: list[CommitSummary] = []
        for line in raw.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append(CommitSummary(*parts))
        return commits

    # ── check ───────────────────────────────────────────────────────────

    def check_for_updates(self) -> UpdateCheckResult:
        """Check for a newer version, by git or by GitHub release."""
        result = self._check_release() if not self.is_git else self._check_git()
        self.check_finished.emit(result)
        return result

    def _check_git(self) -> UpdateCheckResult:

        result = UpdateCheckResult()
        branch = self._config.get("update_branch", "main")

        try:
            self._run_git("fetch", "origin", branch)

            result.current_hash = self._run_git("rev-parse", "--short", "HEAD")
            result.remote_hash = self._run_git("rev-parse", "--short", f"origin/{branch}")

            # Only commits we don't have: a clone that is ahead of
            # origin (local work, another branch) has nothing to pull.
            behind = int(self._run_git("rev-list", "--count", f"HEAD..origin/{branch}"))
            if behind > 0:
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
            log.warning("Update check failed: %s", e)
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            log.error("Update check error", exc_info=True)
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
            for asset in rel.get("assets") or []:
                name = str(asset.get("name") or "")
                if _INSTALLER_ASSET_RE.match(name):
                    result.installer_name = name
                    result.installer_url = str(asset.get("browser_download_url") or "")
                    result.installer_size = int(asset.get("size") or 0)
                    digest = str(asset.get("digest") or "")
                    if digest.lower().startswith("sha256:"):
                        result.installer_sha256 = digest[7:].lower()
                    break
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
            log.warning(result.error)
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

        stashed = False
        try:
            # Stash any local changes so they don't block the pull
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
        except GitError as e:
            result.error = str(e)
            log.error("Update failed: %s", e)
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            log.error("Update error", exc_info=True)
        finally:
            # Put local changes back, also when the pull failed
            if stashed:
                try:
                    self._run_git("stash", "pop")
                    log.info("Restored stashed local changes")
                except GitError:
                    log.warning("Could not restore stashed changes (may have "
                                "conflicts) — they are in `git stash list`")
        return result

    # ── release install ─────────────────────────────────────────────────

    def download_installer(self, result: UpdateCheckResult,
                           progress: Optional[Callable[[int, int], None]] = None,
                           dest_dir: Optional[Path] = None) -> Path:
        """Download the release's setup program; returns its path.

        Checks the size and, when GitHub published one, the SHA-256 digest.
        Raises RuntimeError with an operator-facing message on any failure.
        """
        if not result.installer_url:
            raise RuntimeError("This release has no installer to download.")
        own_dir = dest_dir is None
        dest_dir = Path(dest_dir or tempfile.mkdtemp(prefix="aether-term-update-"))
        dest = dest_dir / (result.installer_name or "Aether_Term_Setup.exe")
        try:
            done = self._download(result, dest, progress)
        except RuntimeError:
            dest.unlink(missing_ok=True)       # nothing half-downloaded is kept
            if own_dir:
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        log.info("Downloaded %s (%d bytes)", dest, done)
        return dest

    @staticmethod
    def _download(result: UpdateCheckResult, dest: Path,
                  progress: Optional[Callable[[int, int], None]]) -> int:
        """Fetch the installer to *dest*, checking size and digest."""
        req = urllib.request.Request(result.installer_url, headers={
            "User-Agent": "AetherTerm-Updater"})
        sha = hashlib.sha256()
        done = 0
        try:
            with urllib.request.urlopen(req, timeout=30,
                                        context=_ssl_context()) as resp, \
                    open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or
                            result.installer_size or 0)
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except Exception as e:
            raise RuntimeError(f"Download failed: {e}") from e
        if result.installer_size and done != result.installer_size:
            raise RuntimeError(
                f"Download incomplete ({done} of {result.installer_size} bytes).")
        if result.installer_sha256 and sha.hexdigest() != result.installer_sha256:
            raise RuntimeError("The downloaded installer failed its checksum "
                               "— not running it.")
        return done

    @staticmethod
    def launch_installer(path: Path):
        """Start the setup program detached; the caller then quits the app."""
        log.info("Launching installer %s %s", path, " ".join(INSTALLER_ARGS))
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(path)] + INSTALLER_ARGS, close_fds=True,
                         creationflags=flags)

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
