# Aether Term — Codebase Audit (October 2026, v1.1.7 → v1.1.8)

A technical-debt pass over the whole repository: dead code, duplicated
implementations, and confirmed bugs, with each fix covered by a test that fails
on the old code where a test was possible. No features were added and the UI was
not redesigned. Wire protocols (VARA TCP, AGWPE, rigctld, FLrig XML-RPC, the BBS
`;AUTH` / `;WLREG` / `;TACTICAL` / `;TRANSPORT` lines) are unchanged.

## Method

1. **Baseline:** the test suite (145 tests, all passing), coverage, pyflakes and
   vulture, all on `main` at v1.1.7.
2. **Architecture mapping and audit.** I read the main window, the VARA and AGWPE
   modems, the terminal and the auth code directly. Three parallel read-only reviews
   covered the radio/PTT clients, auth/passwords/config/profiles, and packaging/updater.
   Every candidate was confirmed by grepping all of `src/` and `tests/`, including signal
   connections and dynamic use, before it was classified.
3. **Changes:** small commits, one subject each, with the full suite run after each.
   Where possible, each fix has a test written first that fails on the old code.

## Metrics

| | Before (v1.1.7) | After |
|---|---|---|
| Source lines, `src/` (all / code only) | 9,786 / 8,004 | 9,020 / 7,357 (−8%) |
| Source modules | 28 | 29 (+`vara/rig_client.py`, −0) |
| Runtime dependencies (`requirements.txt`) | 6 | 5 (pyserial removed) |
| Tests | 145 passing | 171 passing |
| Statement coverage | 65% | 72% |
| pyflakes warnings | 24 | 0 |
| vulture findings (≥60% confidence) | 47 | 11, all false positives (Qt overrides, COM properties, lambda arguments) |
| Diff in `src/` and `tests/` vs v1.1.7 | | 33 files, +1,260 / −1,565 |

The line counts count docstrings as code. Test lines went up (1,666 → 2,050 code
lines); the new tests and fakes are counted there, not in `src/`.

## Five highest-value simplifications (done)

1. **One I/O-thread base for the three rig clients** (`vara/rig_client.py`).
   - Before, OmniRig, Hamlib and FLrig each had a copy of the same command class,
     queue, start/stop and loop, plus a CAT API (frequency, mode, strength, info)
     that nothing called; the Hamlib getters could not have worked.
   - The three files went from 1,186 lines to 473, plus the new 137-line base.
     `PTTController` keeps one rig slot instead of three plus a backend string.
2. **One partial-line path in the terminal.**
   - Two mechanisms displayed unfinished lines: an older "short prompt" path and the
     1.1.3 quiet-pause path. They disagreed about authentication: the 1.1.3 path
     showed "Enter password:" during automatic login.
3. **One way to apply a profile.**
   - Selecting a profile and connecting from the Profiles window were separate code
     paths. They applied different fields, and the dialog path lost the profile entirely
     (see R7).
4. **Readers own their sockets.**
   - The VARA reader threads re-read `self._cmd_sock` / `self._data_sock` on every pass.
     That made them race with disconnects and with the next connection.
5. **Dead code and dependencies removed** across modems, updater, `_frozen.py`,
   passwords, config defaults, the spec, and pyserial.

## Findings

Classification: REMOVE (verified dead), CONSOLIDATE (duplicate logic), REPAIR
(confirmed bug), INVESTIGATE (purpose or impact uncertain), RETAIN (needed, though it
may look redundant). "Done" means fixed in this pass; the commit is named.

### Repaired bugs

| # | Finding | Location | Sev. | Evidence | Action | Risk |
|---|---|---|---|---|---|---|
| R1 | Settings/passwords file that failed to read was overwritten at the next save: all profiles, macros or saved passwords lost | `config.load`, `PasswordStore._load` | High | Test writes a corrupt file, then saves | Done: the file is set aside as `*.unreadable-<time>`, startup says so, and writes are atomic (eda948b) | Low |
| R2 | VARA HF Disconnect released PTT before VARA sent its disconnect frames: the other station never heard the link end | `MainWindow._on_disconnect` | High | Fake VARA keys PTT around its disconnect; the radio was not keyed | Done: PTT is released when the link is down (d36b979) | Low |
| R3 | Soundmodem quitting or crashing left a "connected" session | `AGWPEClient` reader | High | Fake Soundmodem stop; the state stayed CONNECTED | Done: `on_lost` callback, so the modem link reads as closed (d36b979) | Low |
| R4 | AGWPE connect timeout of an abandoned call failed the next call; timeout did not cancel the call, so Soundmodem kept calling on air; Disconnect while calling did not cancel either | `AGWPEModem.rf_connect` | Medium | Tests | Done: per-call timer, `d` frame on timeout and on disconnect; 30 s raised to 60 s (a 1200-baud call through a digipeater took 14 s on air) (d36b979) | Low |
| R5 | Rig `start()` reported success when its wait ran out while still connecting: "PTT connected" and an unkeyed call | all three rig clients | Medium | `SlowRig` test | Done (cc030db) | Low |
| R6 | A stale queued PTT ON could key the radio after `stop()` | `PTTController.stop` | Medium | Test with a slow rig | Done: the queue is drained, then the radio unkeyed (cc030db) | Low |
| R7 | Connect from the Profiles window: closing the window reset the profile just connected, so the call went out under the global callsign, wrong password key, no tactical address | `_open_profiles` → `_refresh_profiles` | High | Test | Done: rebuild blocks signals and keeps the selection (bba67f3) | Low |
| R8 | "Enter password:" shown during automatic HMAC login on slow links | `_show_partial_line` | Low | Test | Done (bba67f3) | Low |
| R9 | New `Config` objects shared the default `profiles`/`macros` lists: a profile added to one appeared in later ones | `Config.__init__` | Medium | Found by the R7 test; own test | Done: deep copy (bba67f3) | Low |
| R10 | Hamlib: rigctld stderr piped and never read (a chatty rigctld could stall PTT); a timed-out reply read as the next command's answer; a failed launch reported as "Is rigctld running?" | `vara/hamlib.py` | Medium | Late-reply test, silent-rigctld test | Done (cc030db) | Low |
| R11 | FLrig changed the process-wide socket timeout, then ran with none (a hung FLrig hung the I/O thread) | `vara/flrig.py` | Low | Code | Done: per-connection transport timeout (cc030db) | Low |
| R12 | Reader threads followed `self._*_sock` to None (AttributeError on the thread) or to the next connection, and an old reader could report "Lost connection" for the new one | `VARAModem` readers | Medium | Test | Done (d36b979) | Low |
| R13 | UTF-8 character split across TCP reads or AX.25 frames became two replacement characters | both modems | Low | Test | Done: incremental decoders (d36b979) | Low |
| R14 | Git installs: "Update & Restart" relaunched a relative `src\main.py` from another directory and never came back | `MainWindow._restart` | High | Test | Done (72ae951) | Low |
| R15 | Git update: a failed pull left local changes in the stash; a clone ahead of origin was always offered an "update" | `Updater` | Medium | Tests against a local origin | Done (72ae951) | Low |
| R16 | Failed installer download left files in %TEMP%; the update dialog could be closed mid-download and still launch the installer | `Updater`, `UpdateDialog` | Low | Test; code | Done (72ae951) | Low |
| R17 | The v1.0→v1.1 exe-path migration ran at every start, undoing a cleared path / auto-launch | `Config._migrate` | Medium | Test | Done: runs once (eda948b) | Low |
| R18 | Settings → Max Retries was saved and never used | `VARAModem._do_connect` | Low | Test | Done (eda948b) | Low |
| R19 | "Plaintext fallback" setting and auth mode claimed a password would be sent in plaintext; nothing did (or should) | settings and password dialogs | Medium | Grep: no reader | Done: controls removed, stored values untouched (eda948b) | Low |
| R20 | Hamlib download: archive entries such as `../x` written outside the install folder; unverified-TLS fallback; rigctld path never filled in after install (dialog never "accepts") | `hamlib_download.py`, `hamlib_settings.py` | Medium | Zip test; code | Done (dd43f98) | Low |
| R21 | Installed build: a fatal startup error was only printed (no console) | `main.py` | Medium | Code | Done: dialog (dd43f98) | Low |
| R22 | AGWPE: my R3 change let the reader clear `_client` under a GUI-thread disconnect: abort | `AGWPEModem` | High (introduced and fixed in this pass) | Main-window tests aborted | Done: one read per use (5ab7ed6) | Low |

### Removed (verified dead)

| Item | Where | Evidence |
|---|---|---|
| CAT API: set/get freq, mode, strength, info, `get_tx`, status-name chain, `ST_*`/`RIG_OK` | rig clients, `ptt.py` | No caller in src/tests |
| `use_hamlib_client` / `use_flrig_client` / `_shared_*` | `ptt.py` | No caller; would also have skipped the release on stop |
| `raw_data_received`, `send_data_bytes`, `remote_call`, `_lock`, `CMD_ACK_TIMEOUT` | modems | No consumer / caller |
| `request_port_info` and its `g` handler | AGWPE | Never sent |
| `_aether_status`, `_detected_transport`, `_send_macro`, debug log lines | main window | Written, never read |
| `set_history` / `get_history` | terminal widget | No caller |
| `remove_password`, `has_password` | passwords | No caller (dialog uses `remove_by_key`) |
| `update_failed`, `last_check`, commit date | updater | No listener / reader |
| `BUNDLE_DIR`, `APP_DIR`, `RESOURCE_DIR`, `is_frozen`; `src/resources/` | `_frozen.py`, spec | Only `EXE_DIR` used |
| `theme`, `command_history_size` defaults | config | Never read (users' stored values are kept) |
| pyserial; spec hidden imports for serial, cryptography KDF/HMAC, win32api | requirements, spec, scripts | Never imported |
| 24 unused imports | throughout | pyflakes |

### Retained deliberately

- **VARA Term migration** (`_app_data_dir` copytree, `"VARA Term"` keyring service,
  `VTermSalt2026` salt, installer AppId and `[InstallDelete]`): still needed by anyone
  upgrading from VARA Term. Changing the key identifiers would make every saved
  password unreadable.
- **Separate VARA and AGWPE modem classes:** the protocols differ (two sockets with
  text commands, against one binary frame stream). They share a signal interface and
  nothing more would be gained by forcing them together.
- **`PTTController.ptt_on`, `AetherQuery.pending`, `AetherStatus.answering`:** used by
  tests, or part of the parsed control-API record.

## Remaining technical debt (ranked)

| # | Issue | Impact | Complexity | Risk of fixing |
|---|---|---|---|---|
| D1 | **Saved-password encryption uses a constant key** (default passphrase, fixed salt; the keyring only stores the same default). Anyone with the file and the source can decrypt it. A real fix needs a random keyring key, re-encryption, and a fallback to the old key. | High (security) | Medium | High if done carelessly; needs your decision |
| D2 | **Auth lines are honoured anywhere in the session:** a message or bulletin containing `;AUTH HMAC-SHA256 <hex>` makes Aether Term answer, and `;AUTH OK` shows a fake success. Limiting this to the login phase is a protocol decision. | Medium | Low | Medium (interop with Aether BBS) |
| D3 | **PTT start/stop run on the GUI thread:** up to ~20 s with Hamlib auto-launch against an unresponsive rig, and the window freezes meanwhile. Moving them to a worker means an asynchronous connect step. | Medium | Medium | Medium |
| D4 | **Choosing a profile writes its bandwidths into the global settings** (`fm_bandwidth`, `hf_bandwidth`, `aether_bandwidth`), so they persist after the profile is deselected. Fixing it means session overrides read wherever config is read. | Low–Medium | Medium | Medium |
| D5 | **`main_window.py` is still ~2,150 lines.** Natural seams: modem-process launching, BBS stream handling (line ends, partials, auth dispatch), Aether HF status. Splitting is low value until something else needs those pieces. | Low | Medium | Medium |
| D6 | **WLREG encrypts the Winlink password by XOR with SHA-256(BBS password + nonce).** Anyone who knows a shared BBS password can decrypt it, and the scheme may count as encryption under §97.113. Protocol owned by Aether BBS. | Medium | — | — |
| D7 | **`.bat` files are stored with LF line endings.** cmd.exe can mis-parse `goto` labels in LF files; `setup_term.bat` is downloaded raw. They work on the maintainer's machines today. Changing their endings should be tested on Windows first. | Low (unconfirmed) | Low | Low |
| D8 | **Hypothesis, untested:** a silent update of an all-users (Program Files) install may land as a second per-user copy; the updater passes no `/ALLUSERS`/`/CURRENTUSER`. | Medium if true | Low | Low |
| D9 | **Hypothesis:** if the updater finds no SHA-256 digest it checks only the download size (GitHub publishes one today). | Low | Low | Low |
| D10 | **The terminal scrollback is unbounded.** A days-long session grows memory. | Low | Low | Low (behaviour change) |
| D11 | **Hamlib download wipes the old install before extracting.** A failed extract leaves nothing. | Low | Low | Low |
| D12 | **Legacy password lookup tries the SSID-stripped call before the exact one** (the operator-keyed lookup does the opposite). Changing the order changes which password is used. | Low | Low | Medium |

## Interoperability verification

**Automatically verified (pytest, 171 tests, Linux and Windows CI):**
- the parsers for VARA events, AGWPE frames and the Aether HF control API;
- HMAC computation and its line handling;
- line-ending learning (CR, LF, CR LF) and partial lines;
- config migration and corruption handling, password-store safety;
- updater version logic, release download and checksum, git mode against a local origin;
- profile, mode and macro UI behaviour.

**Verified against simulated endpoints:**
- **VARA FM, VARA HF and Aether HF:** connect, refusal, rejection, digipeated connect,
  modem crash, BPQ-style bare-CR node, P2P/Winlink session, PTT ordering and release,
  disconnect keying (`tests/fake_aetherd.py`).
- **Soundmodem / AGWPE:** connect, `v` digipeater connect, data, quit, unanswered call,
  cancel (`tests/fake_agwpe.py`).
- **Rig control:** rigctld (including silent and late replies) and FLrig
  (`tests/fake_rigs.py`).

**Still needs real equipment or on-air testing:**
- OmniRig (COM, Windows only, no test coverage);
- Hamlib with a real rigctld and radio; FLrig with a real radio;
- the Hamlib download itself (needs network and GitHub assets);
- VARA HF's own disconnect keying on air (R2);
- Soundmodem link loss and call cancel (R3, R4) with the real Windows Soundmodem 1.14;
- BPQ32 and Aether BBS sessions after the partial-line consolidation;
- the installer and silent update path (D8);
- the git-mode restart from `start_aether_term.bat` (R14).
