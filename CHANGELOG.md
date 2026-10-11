# Aether Term Changelog

All notable changes to Aether Term (formerly VARA Term) are documented here.
Format: [version] — YYYY-MM-DD, then a bulleted list of changes.

---

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
- The installer keeps VARA Term's AppId, so it upgrades an existing install.

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
- README: a Support section (Tiles on the Air giving page) and the GPL v3
  license statement. The GitHub Sponsor button points at the same page.

### Documentation

- README, build guide, release checklist and the GitHub Pages install page
  rewritten for the new name, Aether HF setup, and upgrading from VARA Term.

### Fixed

- The toolbar mode selector snapped back to VARA FM after closing Settings
  while Soundmodem was selected.
- Connection profiles could not store the Soundmodem (AGWPE) mode.
- The `OK` that Aether HF sends for the cleanup `DISCONNECT` is now absorbed
  during modem init, so init no longer waits for a 2 s timeout.
- `build.bat` referenced a spec file that did not exist, and the release
  workflow passed an unquoted name with a space to PyInstaller.

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

### Fixed

- **[BLOCKING] Silent PTT drop on CAT control failure (HF)** — If FLrig, Hamlib,
  or OmniRig was not running when Connect was clicked, PTTController was never
  enabled and VARA HF PTT ON/OFF events were silently dropped, preventing the
  radio from keying. Connection now aborts immediately with a clear error message
  if the configured PTT backend cannot be reached. A secondary guard in
  `_send_rf_connect()` catches the case where CAT setup was still in-flight
  when the 4-second init timer fired.
  *(gui/main_window.py — `_setup_hf_radio_control()`, `_send_rf_connect()`)*

- **[SIGNIFICANT] `_init_cleanup` race condition in modem init (HF)** — The
  DISCONNECT cleanup at the start of `_do_init()` used a fixed 0.8 s sleep to
  suppress VARA's response. If VARA HF responded after the sleep window closed,
  the resulting DISCONNECTED event was processed normally, emitting a spurious
  `rf_disconnected` signal and printing a false "connection attempt failed"
  message before any connection had been attempted. Replaced the sleep with a
  `threading.Event` that blocks until VARA actually acknowledges (WRONG /
  DISCONNECTED / PTT) or times out after 2 s.
  *(vara/modem.py — `_do_init()`, `_handle_event()`)*

- **[SIGNIFICANT] Config migration silently overriding `hf_ptt_method`** — The
  v1.2→v1.3 migration consumed `flrig_enabled` / `hamlib_enabled` flags to
  set `hf_ptt_method`, but never deleted the flags afterwards. On every
  subsequent launch the migration re-ran and could overwrite a manually chosen
  PTT method. Flags are now deleted after being consumed so the migration runs
  exactly once per install.
  *(config.py — `_migrate()`)*

- **[MINOR] GUI thread blocked during CAT/PTT startup (HF)** — `_start_flrig_cat()`
  and `_start_hamlib_cat()` were called directly from `_on_connect()` on the
  main Qt thread. Each can block for up to 10 s during XML-RPC / socket
  negotiation, freezing the UI and delaying processing of the `modem_connected`
  signal. CAT/PTT setup now runs on a dedicated background thread
  (`RadioControlSetup`). A `_term()` helper posts terminal messages back to
  the main thread via a queued signal.
  *(gui/main_window.py — `_setup_hf_radio_control()`, `_term()`)*

- **[MINOR] Repeated "connection failed" messages during HF retries** — VARA HF
  sends DISCONNECTED for every individual retry attempt. Each event triggered
  `_on_rf_disconnected()` with `was_connected = False`, printing the "attempt
  failed" warning once per retry (up to 5 times). Added a `_retry_warned` flag
  per connect attempt so the message appears only once, replaced by a clearer
  "VARA is retrying..." status.
  *(gui/main_window.py — `_on_rf_disconnected()`)*

---

## [1.0.0] — Initial release
