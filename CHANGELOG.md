# Aether Term Changelog

All notable changes to Aether Term (formerly VARA Term) are documented here.
Format: [version] — YYYY-MM-DD, then a bulleted list of changes.

---

## [1.1.6] — 2026-10-14

### Added

- **FLrig and Hamlib PTT.** Settings → Modem Configuration → HF PTT Control
  now offers *Hamlib (rigctld)* and *FLrig* next to OmniRig and VOX, for
  VARA HF and host-keyed Aether HF. Each method shows only its own
  settings: OmniRig's rig number, FLrig's host and port, or the Hamlib
  panel (rig model, serial port, rigctld address, auto-launch, and the
  Hamlib download). The drivers were already in Aether Term but couldn't be
  selected. *(gui/settings_dialog.py, vara/ptt.py, config.py)*

### Changed

- **Connect stops when PTT can't reach the radio.** It used to go ahead with
  a warning, and the call went out with the radio never keyed. Now, unless
  the PTT method is *None (VOX)*, Aether Term starts PTT before opening the
  modem link. If that fails, the modem is never called, and a dialog says
  why (for example "Cannot connect to FLrig … Is FLrig running?") and how
  to fix it. VARA FM and Soundmodem are unaffected: they key the radio
  themselves. *(gui/main_window.py)*
- The startup "OmniRig not running" notice appears only when OmniRig is
  the PTT method. *(gui/main_window.py)*
- **Soundmodem (AGWPE) traffic is logged.** Every frame Aether Term sends to
  or receives from Soundmodem goes into `aether-term.log` (kind, port,
  calls, PID, length, the first 80 bytes). Heard-traffic monitor frames are
  logged at debug level only. This is for a Soundmodem session through a
  digipeater that connected but passed no data: the log will show whether
  the typed lines reached Soundmodem. *(vara/agwpe.py, vara/agwpe_modem.py)*

---

## [1.1.5] — 2026-10-14

### Fixed

- **The radio can no longer be left keyed by PTT commands running out of
  order.** Each VARA HF `PTT ON` / `PTT OFF` was handed to its own
  background thread. When keying the rig was slow (OmniRig, CAT), a
  `PTT OFF` could run before the `PTT ON` ahead of it and leave the
  transmitter keyed until the 90-second watchdog fired. Keying now runs on
  one worker thread, in the order VARA asked, and the watchdog's forced
  release queues behind it. *(vara/ptt.py)*
- **PTT is released whenever the modem link closes.** If VARA crashed or
  its TCP link dropped mid-transmission, the radio stayed keyed until the
  watchdog fired. A call that failed with `WRONG` or `CANCELPENDING` also
  left the rig link open. Now any end of the modem link unkeys the radio
  and closes the rig link at once. *(gui/main_window.py)*

- **Via boxes show the whole callsign.** In 1.1.4 the Via 1 / Via 2
  dropdowns had only a maximum width, and the toolbar squeezed them to about
  35 px: "None" read "one" and only two letters of a callsign were visible.
  They now always have room for a full call with SSID (`WD5EMA-15`).
  *(gui/main_window.py)*

### Added

- **VARA HF sends `P2P SESSION`.** VARA's command reference says
  `P2P SESSION` "must be used for P2P connections, not for Gateways", and
  VARA HF defaults to `WINLINK SESSION`, a 4-second retry cycle meant for
  Winlink gateways. Calls to a BBS or station now use P2P. A new
  **Settings → Session Type** option switches to *Winlink gateway* for RMS
  calls. VARA FM, Aether HF and Soundmodem are unchanged.
  *(config.py, vara/modem.py, gui/settings_dialog.py)*
- **Digipeaters with Soundmodem (AGWPE).** Via 1 / Via 2 now work in
  Soundmodem mode. The call goes out as AGWPE's "connect via" frame (`v`:
  the digipeater count, then each call), so the path is set per call from
  Aether Term. Soundmodem's own `Digi` settings are for Soundmodem acting as
  a digipeater, and do not route outgoing calls. VARA HF and Aether HF still
  refuse a Via path. *(vara/agwpe.py, vara/agwpe_modem.py, gui/main_window.py)*
- **VARA HF end-to-end tests.** A full session against the fake modem
  covers the init commands, `CONNECTED … 2300`, PTT keying and unkeying
  through a fake rig, release on disconnect, a refused call, a rejected
  `CONNECT`, and a modem crash while keyed. The PTT controller has its own
  tests for ordering, the watchdog and stop. Both modem drivers now ignore
  initialization arguments they don't use, so a new argument can't crash
  one of them again. *(tests/test_vara_hf.py, vara/modem.py,
  vara/agwpe_modem.py)*

## [1.1.4] — 2026-10-13

### Changed

- **Via 1 / Via 2 are dropdowns that remember.** Both boxes offer **None**
  plus the digipeaters you have used before, most recent first, up to 10. You
  can still type a new one. Each call's choice, None included, is saved and
  comes back the next time Aether Term starts, so a digipeated route is not
  lost to an empty box. Picking a profile still fills both boxes.
  *(gui/main_window.py, config.py)*

### Fixed

- **Soundmodem (AGWPE) connects no longer close the app.** Since 1.1.0 the
  window called the modem's initialization with an argument the Soundmodem
  driver didn't accept, and the error inside a Qt event handler made PyQt6
  abort the program the moment the TNC link came up. The driver now takes the
  same arguments as the VARA one and reports its states, so the AX.25 connect
  actually goes out. *(vara/agwpe_modem.py, gui/main_window.py)*
- **AGWPE frames match the spec.** The frame header was packed as 40 bytes
  instead of the AGWPE protocol's 36, which shifted the callsigns, the data
  length and the data by 4 bytes, so Soundmodem could not have understood
  any frame. *(vara/agwpe.py)*
- **Switching modes no longer kills the next call.** When Connect replaced
  the modem (for example VARA FM → Soundmodem), the old modem's final
  "disconnected" reached the window after the new call had started, and the
  idle-link cleanup closed the new link. The old modem is now silenced before
  it is closed, and the Soundmodem driver no longer announces "disconnected"
  at the start of a connect. PTT messages are also no longer doubled after a
  mode switch. *(gui/main_window.py, vara/agwpe_modem.py)*
- **Unexpected errors are logged instead of closing the app.** An error
  inside a Qt event handler is written to the log with its traceback and
  shown in a dialog, and Aether Term keeps running. Errors in background
  threads are logged too. *(main.py)*

## [1.1.3] — 2026-10-13

### Fixed

- **Commands to BPQ nodes work.** Typed lines always ended in CR LF. A BPQ
  node ends a command at the CR and keeps the LF as the first character of
  the next one, so every command after the first arrived garbled. Aether Term
  now answers in the BBS's own convention, learned from what the BBS sends:
  a bare CR for BPQ and most packet nodes, CR LF for the Aether BBS. A BPQ
  node says nothing until spoken to, so the first line goes out with a bare
  CR. A BBS that greets first shows its CR LF before you type.
  *(gui/main_window.py)*
- **Prompts without a line end are shown.** BPQ applications wait at prompts
  such as `1 Check in  2 Check out  3 Roster  4 Back:` with no line end, and
  only short prompts ending in `>` or `:` used to appear. Now any unfinished
  line is shown once the BBS has been quiet for a second. When the rest of the
  line arrives, it continues on the same screen line, so a line VARA split
  across radio frames still reads as one line. *(gui/main_window.py)*
- **No `;TRANSPORT?` to BBSes that don't know it.** The Aether BBS transport
  query used to go out one second after every connect, and a BPQ node read it
  as a bad command. It is now sent only once the BBS has shown CR LF line
  ends, as the Aether BBS does. *(gui/main_window.py)*

## [1.1.2] — 2026-10-13

### Fixed

- **BPQ nodes and other CR-only BBSes now display.** Incoming text was only
  split into lines at LF. A BPQ node ends its lines with a bare CR, so its
  banner, prompts and command replies piled up unseen and the node seemed not
  to answer. CR, LF and CR LF now all end a line, including a CR LF split
  across two chunks. *(gui/main_window.py)*

### Build

- **The release workflow can create the tag.** Run by hand with a tag that
  doesn't exist yet, it builds the selected branch and creates the tag on that
  commit when it publishes the release. An existing tag is still built as it
  is. *(.github/workflows/build_release.yml)*

## [1.1.1] — 2026-10-13

### Added

- **Update prompt at startup.** When a newer version is out, Aether Term asks
  whether to update. Installed builds download the release's setup program,
  verify its size and the SHA-256 digest GitHub publishes, then close and run
  it silently. The installer then starts the new version. Portable builds open
  the download page. Git installs pull and restart, and no longer do so
  silently before the window opens. **Skip This Version** stops the startup
  prompt for that release. The prompt never interrupts a session. There is a
  new Settings → Terminal Setup option to turn the startup check off, and
  Help → Check for Updates now says when you are already up to date.
  *(updater.py, gui/update_dialog.py, gui/main_window.py, main.py,
  installer.iss)*

### Fixed

- **Failed calls close the modem link on their own.** A call that was refused,
  timed out, cancelled (`CANCELPENDING`) or rejected with `WRONG` used to leave
  the app connected to the modem, so Disconnect had to be pressed. The attempt
  now ends with "Connection to X failed — closing the modem link." and the
  window is ready for the next call. *(gui/main_window.py, vara/modem.py)*

- **VARA FM digipeater connects.** Commands to the VARA modem now end in a
  bare CR, as the VARA TNC command reference specifies, instead of CR LF. The
  stray LF ended up at the start of the next command. The digipeater path is
  now built as `CONNECT <me> <target> VIA <digi1> [<digi2>]` from either Via
  field: a call typed only in Via 2 used to go out without the `VIA` keyword.
  Both fields also accept calls separated by spaces or commas, are checked
  against VARA's callsign rules, and allow at most two hops.
  *(vara/modem.py)*
- **Digipeated link reply parsed.** VARA FM answers
  `CONNECTED <src> <dst> via <digis> <bw>`. The status bar used to show
  "BW: via Hz". It now shows the bandwidth, and the terminal shows the path
  (`*** CONNECTED to W1AW-5 via N4XYZ-7 ***`). *(vara/modem.py,
  gui/main_window.py)*
- **Digipeaters refused outside VARA FM.** VARA HF, Aether HF and Soundmodem
  cannot use the Via fields. A call with a path in those modes now stops with
  an explanation instead of going out direct. When VARA reports
  `LINK UNREGISTERED` on a digipeated call, the terminal now notes that VARA FM
  requires a license to use digipeaters. *(gui/main_window.py)*

### Build

- **The release workflow builds the installer.** Publishing a release attaches
  `Aether_Term_Setup_X.Y.Z.exe`, its zip and the portable zip, all built with
  Inno Setup on GitHub's Windows runners. The workflow stops if `version.txt`
  doesn't match the tag. Run by hand with a tag, it creates and publishes the
  release itself, with this CHANGELOG section as its notes. Without a tag it
  does a dry run that keeps the files as workflow artifacts. A test checks that
  `version.txt`, `installer.iss` and the CHANGELOG agree.
  *(.github/workflows/build_release.yml)*

## [1.1.0] — 2026-10-10

### Changed

- **Renamed VARA Term → Aether Term.** The repository is now
  `KK4ODA/aether-term`. The window, installer, executable (`Aether Term.exe`),
  launcher (`start_aether_term.bat`), PyInstaller spec (`aether_term.spec`),
  log file (`~/Aether Term/logs/aether-term.log`) and docs carry the new name.
- **Settings migrate automatically.** On first start, `%APPDATA%\VARA Term\`
  (settings, encrypted station passwords, Hamlib download) is copied to
  `%APPDATA%\Aether Term\`. The old folder is left untouched. The password
  store keeps its original key-derivation identifiers so saved passwords stay
  readable. *(config.py, passwords.py)*
- The installer keeps VARA Term's AppId, so it upgrades an existing install
  in place. It removes the old `VARA Term.exe` and its Start Menu and desktop
  shortcuts, and puts the new shortcuts under "Aether Term". This was tested
  by upgrading over a VARA Term installer built from the pre-rebrand script,
  then uninstalling.

### Added

- **Aether HF modem support** (https://github.com/KK4ODA/aether-hf), as a
  fourth transport next to VARA FM, VARA HF and Soundmodem — in the toolbar,
  Settings and connection profiles. Sessions run over Aether HF's
  VARA-compatible host port (8300/8301), with `BW2300`/`BW500`.
  *(config.py, gui/main_window.py, gui/settings_dialog.py, gui/profile_dialog.py)*
- **Aether HF control-API client** (`aether/control.py`): read-only `status`
  and `capabilities` over `http://127.0.0.1:8515/v1/`. Used for:
  - a live status-bar indicator (version, bandwidth, state, rung, faults),
    polled every 2 s while Aether HF is selected;
  - a **pre-connect check** that stops the call with a plain explanation when
    the host port is off, no rules are chosen, the rules block TX, or keying or
    the sound card has a fault;
  - explaining a call that ended without a session;
  - **Settings → Modem Configuration → Test Aether HF**, and an
    **Aether HF** menu (status, station panel, setup guide, download).
- `VERSION` check after attaching in Aether HF mode, which warns if another
  modem (such as VARA HF) holds the port.
- `BITRATE` link speed and the bandwidth from `CONNECTED` in the status bar
  (any VARA-protocol modem that sends them). `MISSING SOUNDCARD` is reported.
- Optional Aether HF auto-launch (`%LOCALAPPDATA%\Aether HF\aether-hf.exe`),
  skipped when Aether HF is already running.
- Aether HF keying option: PTT from Aether Term only when Aether HF's keying
  is set to "host program". By default Aether HF keys the radio itself, and
  its regulatory check stays on.
- `docs/AETHER_HF.md` documents the protocol mapping.
- **Updates for installed builds.** The installer and portable builds have no
  `.git`, so the git-based updater could never update them. They now check the
  latest GitHub release on startup, show `UPDATE vX.Y.Z` in the status bar,
  and open the release's download page with its notes. Git installs still
  pull and restart as before. *(updater.py, gui/update_dialog.py, main.py)*
- **Test suite and CI.** `tests/` has 57 pytest tests: settings migration,
  the event parser, the Aether HF control client, the release updater, and the
  main window end to end against a fake Aether HF daemon
  (`tests/fake_aetherd.py`). They run on Windows and Ubuntu on every push and
  pull request (`.github/workflows/tests.yml`).
- README: a Support section (Tiles on the Air giving page) and the GPL v3
  license statement. The GitHub Sponsor button points at the same page.

### Documentation

- README, build guide, release checklist and the GitHub Pages install page
  rewritten for the new name, Aether HF setup, and upgrading from VARA Term.

### Fixed

- Aether HF status checks (before a call, after a refused call, the status
  dialog, auto-launch and the Settings test button) run on a worker thread.
  A slow or unreachable modem no longer freezes the window, and Connect stays
  disabled while the check is out.
- `pywin32` is installed only on Windows, so `pip install -r requirements.txt`
  works on Linux.
- The toolbar mode selector snapped back to VARA FM after closing Settings
  while Soundmodem was selected.
- Connection profiles could not store the Soundmodem (AGWPE) mode.
- The `OK` that Aether HF sends for the cleanup `DISCONNECT` is now absorbed
  during modem init, so init no longer waits for a 2 s timeout.
- `build.bat` referenced a spec file that did not exist. The release
  workflow passed an unquoted name with a space to PyInstaller and had no
  permission to attach its build. It now attaches
  `Aether_Term_Portable_<version>.zip` to each release.

---

## [1.0.3] — 2026-04-11

`version.txt` read 1.0.3 from the first commit, and these changes went in
without a version bump. They are collected here from the commit history.

### Added

- **Encrypted Winlink registration (WLREG)**: the Winlink password is asked
  for locally and sent encrypted with the BBS password and a nonce, never
  in clear over RF.
- **Soundmodem / AGWPE transport**: AX.25 packet via Soundmodem, Direwolf or
  any AGWPE-compatible TNC, as a third mode in the toolbar with auto-launch.
- **Git-based auto-updater**: checks GitHub on startup, pulls and restarts
  before the GUI opens, and has a status-bar indicator and an update dialog
  (Help → Check for Updates). Local changes are stashed before pulling.
- **Operator profiles**: profiles carry their own callsign and SSID. Station
  passwords are stored per operator (`OPERATOR@TARGET`); old target-only
  entries still work.
- **Tactical addresses**: a profile can send `;TACTICAL <call>` after
  authentication, and `;TACTICAL OK/FAIL` replies are shown.
- BBS transport detection (`;TRANSPORT?` after connect) and a chat-room
  indicator in the status bar.
- One-command Windows setup (`setup_term.bat`) that installs Git and Python
  through winget when missing, and a GitHub Pages install page.
- OmniRig availability check at startup.
- Modem connect retry (5 attempts, 2 s apart) for modems that start slowly.
- Clear button, tooltips on all non-obvious settings, richer profile labels,
  and an updated BBS commands reference (S/SW, KA, WL, TACTICAL).

### Changed

- Renamed VTerm → VARA Term, with data under `%APPDATA%\VARA Term`.
- FM bandwidth defaults to WIDE; profiles store it.
- Default HF PTT method is OmniRig.
- The data port is read-only in Settings (always command port + 1).
- 1.5 s turnaround delay before the HMAC auth response.

### Fixed

- HF init race: `CONNECT` now waits for init to finish instead of a fixed
  4 s timer.
- `LISTEN OFF` removed from modem init; it broke data flow.
- Modem process trees are killed on exit (`taskkill /F /T`).
- Clean modem disconnect when switching between FM and HF.
- Elecraft K4 Hamlib model ID (2048 → 2047).
- FLrig PTT verification always returned success; its XML-RPC calls now
  time out.
- Signals left blocked after an exception; Hamlib download worker not
  cleaned up on dialog close; session log file leak.
- Empty commands are no longer sent over RF.
- PTT-disabled warnings in FM mode are logged at debug level.

---

## [1.0.1] — 2026-03-06

This release predates the repository (first commit 2026-03-09). Only the fix
below can be traced in this repository's code. Earlier versions of this entry
also listed connect-time FLrig/Hamlib PTT setup, a background radio-control
thread, a `hf_ptt_method` config migration and a retry-message flag. None of
that code is in this repository, so those items have been removed.

### Fixed

- **`_init_cleanup` race in modem init** — Before `MYCALL`, init sends a
  `DISCONNECT` to clear any session left over from a previous run, and
  suppresses the modem's reply. A fixed 0.8 s sleep used to cover this. When
  VARA answered later than that, its `DISCONNECTED` was handled as a real
  event, and a false "connection attempt failed" appeared before any call was
  made. The sleep is now a `threading.Event` that waits until the modem
  acknowledges (`WRONG`, `DISCONNECTED` or `PTT`), or 2 s at most.
  *(vara/modem.py — `_do_init()`, `_handle_event()`)*

### Known gaps (as of 1.1.0)

- Only OmniRig is wired up for PTT. `vara/ptt.py` has FLrig and Hamlib
  back ends, and `gui/hamlib_settings.py` has a Hamlib settings panel, but
  neither is reachable from the GUI.
- If OmniRig cannot be reached on Connect, the connection goes ahead with a
  warning to use VOX. It does not stop.

---

## [1.0.0] — Initial release
