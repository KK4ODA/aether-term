# RELEASE CHECKLIST

Use this checklist whenever publishing a new version of Aether Term.

------------------------------------------------------------------------

## 1. Prepare the Update

☐ Ensure all intended improvements and bug fixes are complete\
☐ Test the application locally\
☐ Verify the GUI works at normal window sizes\
☐ Confirm no obvious regressions\
☐ Connect once in each mode you can test — including Aether HF against a
current Aether HF build, if its host interface or control API changed

------------------------------------------------------------------------

## 2. Update Version Number

☐ Update `version.txt` and `MyAppVersion` in `installer.iss`\
☐ Follow Semantic Versioning:

MAJOR.MINOR.PATCH

Examples:

1.0.1 -- Bug fixes\
1.1.0 -- New features\
2.0.0 -- Major changes

------------------------------------------------------------------------

## 3. Update Documentation

☐ Add new entry to `CHANGELOG.md`\
☐ Update README if new features were added

Example:

Version 1.0.3

-   Improved settings GUI
-   Fixed scrolling issue
-   Added diagnostics tab

------------------------------------------------------------------------

## 4. Commit Changes (GitHub Desktop)

Open GitHub Desktop and:

☐ Review changed files\
☐ Add commit summary (example: "Prepare release 1.0.3")\
☐ Commit to main\
☐ Push to origin

------------------------------------------------------------------------

## 5. Create GitHub Release

On GitHub:

☐ Open repository\
☐ Click **Releases**\
☐ Click **Create new release**

Fill in:

Tag version: `vX.Y.Z`\
Release title: `Aether Term X.Y.Z`

------------------------------------------------------------------------

## 6. Upload Release Files

Attach:

☐ Installer (`Aether_Term_Setup_X.Y.Z.exe`) and portable zip. Keep the installer's file name:
  the in-app updater looks for the `Aether_Term_Setup_*.exe` asset on the latest release.
(`Aether_Term_Portable_X.Y.Z.zip`) from `build.bat` — the release workflow
also attaches a portable zip automatically\
☐ Source code archive (optional)

------------------------------------------------------------------------

## 7. Publish Release

☐ Click **Publish Release**

Users can now download the new version.

------------------------------------------------------------------------

## 8. Post‑Release Verification

☐ Download the release from GitHub\
☐ Confirm executable runs correctly\
☐ Verify version number appears correctly in the app

------------------------------------------------------------------------

Release complete.
