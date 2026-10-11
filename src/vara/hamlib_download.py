"""
vara/hamlib_download.py — Auto-download and update Hamlib binaries for Aether Term.

Downloads the latest Hamlib release from the official GitHub repository
(https://github.com/Hamlib/Hamlib/releases) and extracts it to the
Aether Term application data directory.

The module uses GitHub's releases API to find the latest version,
compares it to the locally installed version, and downloads the
appropriate platform binary if an update is available.

Usage (from a background thread or async context):
    downloader = HamlibDownloader(install_dir=Path("C:/Users/.../Aether Term/hamlib"))
    info = downloader.check_update()
    if info["update_available"]:
        downloader.download_and_install(progress_callback=my_fn)
"""

import io
import json
import logging
import os
import platform
import re
import shutil
import ssl
import zipfile
import tarfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

log = logging.getLogger(__name__)

GITHUB_API_RELEASES = "https://api.github.com/repos/Hamlib/Hamlib/releases/latest"
USER_AGENT = "AetherTerm-HamlibUpdater/1.0"


def _make_ssl_context():
    """Create an SSL context that works in both source and frozen mode.

    PyInstaller-frozen apps may not find the default CA bundle,
    so we fall back to an unverified context as a last resort.
    """
    # Try default first
    try:
        ctx = ssl.create_default_context()
        # Quick test: can we load the certs?
        if ctx.get_ca_certs():
            return ctx
        return ctx  # Even if empty, might still work
    except Exception:
        pass

    # Try certifi if available
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except Exception:
        pass

    # Last resort: unverified (still encrypted, just no cert check)
    log.warning("SSL: Using unverified context (no CA bundle found)")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class HamlibDownloader:
    """Manages Hamlib binary downloads and installation."""

    def __init__(self, install_dir: Optional[Path] = None):
        if install_dir is None:
            # Default: <Aether Term app data>/hamlib
            if os.name == "nt":
                base = Path(os.environ.get(
                    "APPDATA",
                    Path.home() / "AppData" / "Roaming"))
            else:
                base = Path.home() / ".config"
            install_dir = base / "Aether Term" / "hamlib"
        self._install_dir = Path(install_dir)
        self._version_file = self._install_dir / "version.json"

    @property
    def install_dir(self) -> Path:
        return self._install_dir

    @property
    def rigctld_path(self) -> str:
        """Return path to rigctld executable if installed."""
        if os.name == "nt":
            p = self._install_dir / "bin" / "rigctld.exe"
        else:
            p = self._install_dir / "bin" / "rigctld"
        return str(p) if p.exists() else ""

    @property
    def installed_version(self) -> str:
        """Return the currently installed Hamlib version, or '' if none."""
        if self._version_file.exists():
            try:
                data = json.loads(self._version_file.read_text(encoding="utf-8"))
                return data.get("version", "")
            except Exception:
                pass
        return ""

    def check_update(self) -> Dict[str, Any]:
        """Check GitHub for the latest Hamlib release.

        Returns a dict with:
            latest_version: str     — e.g. "4.6"
            current_version: str    — currently installed, or ""
            update_available: bool  — True if newer version exists
            download_url: str       — direct URL to the platform asset
            asset_name: str         — filename of the asset
            release_notes: str      — release body text (truncated)
            error: str              — error message if check failed
        """
        result = {
            "latest_version": "",
            "current_version": self.installed_version,
            "update_available": False,
            "download_url": "",
            "asset_name": "",
            "release_notes": "",
            "error": "",
        }

        try:
            req = Request(GITHUB_API_RELEASES,
                          headers={"User-Agent": USER_AGENT})
            ctx = _make_ssl_context()
            with urlopen(req, timeout=15, context=ctx) as resp:
                release = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            result["error"] = f"Cannot reach GitHub: {e}"
            log.error(result["error"])
            return result
        except Exception as e:
            result["error"] = f"GitHub API error: {e}"
            log.error(result["error"])
            return result

        tag = release.get("tag_name", "")
        # Hamlib tags are like "4.6" or "v4.6" or "Hamlib-4.6"
        version = re.sub(r"^[vV]?(Hamlib-?)?", "", tag).strip()
        result["latest_version"] = version
        result["release_notes"] = (release.get("body", "") or "")[:500]

        # Find the right asset for this platform
        asset_url, asset_name = self._find_platform_asset(
            release.get("assets", []))
        result["download_url"] = asset_url
        result["asset_name"] = asset_name

        if not asset_url:
            result["error"] = (
                f"No Hamlib binary found for {platform.system()} "
                f"{platform.machine()} in release {version}")
            return result

        # Compare versions
        current = self.installed_version
        if current and version:
            result["update_available"] = self._version_newer(version, current)
        elif version and not current:
            result["update_available"] = True

        return result

    def download_and_install(
        self,
        url: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Download and install Hamlib from the given URL (or auto-detect).

        progress_callback(bytes_downloaded, total_bytes, status_message)

        Returns dict with:
            success: bool
            version: str
            error: str
        """
        result = {"success": False, "version": "", "error": ""}

        if not url:
            info = self.check_update()
            if info["error"]:
                result["error"] = info["error"]
                return result
            url = info["download_url"]
            result["version"] = info["latest_version"]

        if not url:
            result["error"] = "No download URL available"
            return result

        if progress_callback:
            progress_callback(0, 0, "Downloading Hamlib...")

        try:
            # Download
            req = Request(url, headers={"User-Agent": USER_AGENT})
            ctx = _make_ssl_context()
            with urlopen(req, timeout=120, context=ctx) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                data = bytearray()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if progress_callback:
                        progress_callback(len(data), total, "Downloading...")
        except Exception as e:
            result["error"] = f"Download failed: {e}"
            log.error(result["error"])
            return result

        if progress_callback:
            progress_callback(len(data), len(data), "Extracting...")

        # Extract
        try:
            self._install_dir.mkdir(parents=True, exist_ok=True)

            # Clear old installation (preserve version.json until success)
            for item in self._install_dir.iterdir():
                if item.name == "version.json":
                    continue
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)

            filename = url.split("/")[-1].lower()
            buf = io.BytesIO(bytes(data))

            if filename.endswith(".zip"):
                self._extract_zip(buf)
            elif filename.endswith((".tar.gz", ".tgz")):
                self._extract_tarball(buf)
            elif filename.endswith(".tar.xz"):
                self._extract_tarball(buf, mode="r:xz")
            else:
                result["error"] = f"Unknown archive format: {filename}"
                return result

        except Exception as e:
            result["error"] = f"Extraction failed: {e}"
            log.error(result["error"])
            return result

        # Make binaries executable on Unix
        if os.name != "nt":
            bin_dir = self._install_dir / "bin"
            if bin_dir.exists():
                for f in bin_dir.iterdir():
                    if f.is_file():
                        f.chmod(f.stat().st_mode | 0o755)

        # Save version info
        version = result.get("version", "")
        if not version:
            # Try to detect from rigctld --version
            version = self._detect_installed_version()
        self._save_version(version)
        result["version"] = version
        result["success"] = True

        if progress_callback:
            progress_callback(len(data), len(data),
                              f"Hamlib {version} installed successfully")

        log.info(f"Hamlib {version} installed to {self._install_dir}")
        return result

    # ── Private helpers ───────────────────────────────────────────

    def _find_platform_asset(self, assets: list) -> tuple:
        """Find the appropriate binary asset for the current platform.

        Returns (download_url, filename) or ('', '').
        """
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Build platform search patterns
        if system == "windows":
            # Hamlib Windows releases are usually named like:
            # hamlib-w64-4.6.zip or hamlib-win64-4.6.zip
            patterns = [
                r"hamlib.*w(in)?64.*\.zip",
                r"hamlib.*win.*64.*\.zip",
                r"hamlib.*windows.*\.zip",
            ]
            if "32" in machine or machine in ("x86",):
                patterns.insert(0, r"hamlib.*w(in)?32.*\.zip")
        elif system == "darwin":
            patterns = [
                r"hamlib.*macos.*\.(tar\.gz|tgz|zip)",
                r"hamlib.*darwin.*\.(tar\.gz|tgz|zip)",
                r"hamlib.*osx.*\.(tar\.gz|tgz|zip)",
            ]
        else:  # Linux
            arch_map = {"x86_64": "amd64|x86_64", "aarch64": "arm64|aarch64"}
            arch_pattern = arch_map.get(machine, machine)
            patterns = [
                rf"hamlib.*linux.*({arch_pattern}).*\.(tar\.gz|tgz|tar\.xz)",
                r"hamlib.*linux.*\.(tar\.gz|tgz|tar\.xz)",
            ]

        for asset in assets:
            name = asset.get("name", "").lower()
            url = asset.get("browser_download_url", "")
            for pat in patterns:
                if re.search(pat, name):
                    return (url, asset["name"])

        # Fallback: return first zip/tar asset
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith((".zip", ".tar.gz", ".tgz")):
                return (asset["browser_download_url"], asset["name"])

        return ("", "")

    def _extract_zip(self, buf: io.BytesIO):
        """Extract a zip archive, handling nested directories."""
        with zipfile.ZipFile(buf) as zf:
            # Check if there's a single top-level directory
            top_dirs = {n.split("/")[0] for n in zf.namelist() if "/" in n}
            strip_prefix = ""
            if len(top_dirs) == 1:
                strip_prefix = top_dirs.pop() + "/"

            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if strip_prefix and name.startswith(strip_prefix):
                    name = name[len(strip_prefix):]
                if not name:
                    continue
                dest = self._install_dir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _extract_tarball(self, buf: io.BytesIO, mode: str = "r:gz"):
        """Extract a tar archive, handling nested directories."""
        with tarfile.open(fileobj=buf, mode=mode) as tf:
            members = tf.getmembers()
            # Detect single top-level directory
            top_dirs = {m.name.split("/")[0] for m in members
                        if "/" in m.name}
            strip_prefix = ""
            if len(top_dirs) == 1:
                strip_prefix = top_dirs.pop() + "/"

            for member in members:
                if member.isdir():
                    continue
                name = member.name
                if strip_prefix and name.startswith(strip_prefix):
                    name = name[len(strip_prefix):]
                if not name:
                    continue
                dest = self._install_dir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(member)
                if f:
                    with open(dest, "wb") as dst:
                        shutil.copyfileobj(f, dst)

    def _detect_installed_version(self) -> str:
        """Try to run rigctld --version to detect version."""
        rigctld = self.rigctld_path
        if not rigctld:
            return "unknown"
        try:
            import subprocess
            result = subprocess.run(
                [rigctld, "--version"],
                capture_output=True, text=True, timeout=5)
            # Output is like: rigctld, Hamlib 4.6
            m = re.search(r"Hamlib\s+(\S+)", result.stdout + result.stderr)
            return m.group(1) if m else "unknown"
        except Exception:
            return "unknown"

    def _save_version(self, version: str):
        """Persist installed version metadata."""
        data = {"version": version, "install_dir": str(self._install_dir)}
        try:
            self._version_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to save version file: {e}")

    @staticmethod
    def _version_newer(latest: str, current: str) -> bool:
        """Compare version strings.  Returns True if latest > current."""
        def parse(v):
            parts = re.findall(r"\d+", v)
            return tuple(int(p) for p in parts) if parts else (0,)
        return parse(latest) > parse(current)
