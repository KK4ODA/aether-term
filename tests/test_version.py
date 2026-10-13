"""The version is written in two places; a release needs them to agree."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_installer_version_matches_version_txt():
    version = (ROOT / "version.txt").read_text().strip()
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r'#define MyAppVersion "([^"]+)"', iss)
    assert m and m.group(1) == version


def test_changelog_has_an_entry_for_this_version():
    version = (ROOT / "version.txt").read_text().strip()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version}]" in changelog
