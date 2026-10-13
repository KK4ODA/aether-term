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

☐ Update `version.txt` and `MyAppVersion` in `installer.iss` (a test checks
they match)\
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

## 6. Release Files

Nothing to attach by hand: when the release is published, the **Build Aether
Term Release** workflow builds on Windows and attaches

☐ `Aether_Term_Setup_X.Y.Z.exe` — the in-app updater downloads this file, so
  keep its name\
☐ `Aether_Term_Setup_X.Y.Z.zip` (the installer, zipped for sharing)\
☐ `Aether_Term_Portable_X.Y.Z.zip`

It stops if `version.txt` does not match the tag. To try the build before
tagging, run the workflow by hand with an empty tag: the files are kept as
workflow artifacts. `build.bat` builds the same files locally.

Alternatively, push the tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) and run
the workflow by hand with that tag: it creates and publishes the release
itself, titled "Aether Term X.Y.Z" with the CHANGELOG section as its notes.

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
