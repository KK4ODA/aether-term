# Aether Term User Manual

For Aether Term 1.1.10. Aether Term was called *VARA Term* before 1.1.

This manual covers day-to-day use of the program. The [README](../README.md) is the short
version. Aether HF has its own [integration notes](AETHER_HF.md), building the Windows installer
is covered in the [build guide](BUILD_GUIDE.md), and every change by version is in the
[changelog](../CHANGELOG.md).

## Contents

1. [Overview](#1-overview)
2. [Installing and updating](#2-installing-and-updating)
3. [First start](#3-first-start)
4. [The main window](#4-the-main-window)
5. [Connecting](#5-connecting)
6. [Logging in to the BBS](#6-logging-in-to-the-bbs)
7. [Profiles, macros, history and session logs](#7-profiles-macros-history-and-session-logs)
8. [Settings reference](#8-settings-reference)
9. [Working with Aether BBS](#9-working-with-aether-bbs)
10. [Troubleshooting](#10-troubleshooting)
11. [Keyboard and command line](#11-keyboard-and-command-line)

---

## 1. Overview

Aether Term is a terminal for connecting to amateur radio BBS systems. You type commands, the
BBS answers, and Aether Term shows the session in a scrolling window. It is a Windows program
first (it also runs from source on Linux), written in Python with PyQt6.

Aether Term does not contain a modem. It drives a separate modem program over TCP on the same
PC (or another PC on your network), or a KISS TNC such as the one built into a radio:

| Mode (toolbar) | Modem program | Interface | Who keys the radio |
|---|---|---|---|
| **VARA FM** | VARA FM | VARA TCP host interface, ports 8300/8301 | VARA FM |
| **VARA HF** | VARA HF | VARA TCP host interface, ports 8300/8301 | Aether Term (OmniRig, Hamlib, FLrig) or VOX |
| **Aether HF** | [Aether HF](https://github.com/KK4ODA/aether-hf) | VARA-compatible host port 8300/8301, plus its control API on 8515 | Aether HF itself, or Aether Term when Aether HF is set to "host program" keying |
| **Soundmodem** | Soundmodem, Direwolf or any AGWPE TNC | AGWPE, port 8000 | The TNC |
| **KISS TNC** | none: the radio's or TNC's own modem | KISS over a COM port (USB or Bluetooth), Bluetooth LE, or TCP | The radio or TNC |
| **Local test** | none | Aether Term plays a VARA FM modem on 127.0.0.1, ports 8500/8501 | Nothing is transmitted |

What it adds on top of a plain terminal:

- **Automatic login** to BBSes that use HMAC-SHA256 challenge-response (the Aether BBS does).
  The password is stored on your PC and never goes over the air.
- **Encrypted Winlink registration** (`WLREG`) for checking Winlink mail through the BBS.
- **Radio keying for VARA HF** through OmniRig, Hamlib rigctld or FLrig.
- **Aether HF status and pre-call checks** read from Aether HF's control API.
- Connection **profiles**, **macro buttons**, target and digipeater **history**, an S/N graph,
  and per-session **log files**.

With the Aether BBS, Aether Term also asks the BBS what kind of link it sees (`;TRANSPORT?`),
can activate a tactical address (`;TACTICAL`), and shows when you are in a chat room. See
[Working with Aether BBS](#9-working-with-aether-bbs).

Aether Term also works with BPQ nodes and other packet BBSes: it learns the BBS's line endings
(bare CR or CR LF) from what the BBS sends and answers the same way.

---

## 2. Installing and updating

### 2.1 Ways to install

**Windows installer.** Download `Aether_Term_Setup_X.Y.Z.exe` from the
[Releases page](https://github.com/KK4ODA/aether-term/releases) and run it. It adds a Start Menu
entry and an uninstaller. It upgrades an existing VARA Term installation in place.

**Portable zip.** Download `Aether_Term_Portable_X.Y.Z.zip` from the same page, extract it
anywhere, and run `Aether Term.exe`.

**One-line installer (git install).** Open PowerShell and paste the command from the
[project page](https://kk4oda.github.io/aether-term/):

```powershell
irm https://raw.githubusercontent.com/KK4ODA/aether-term/main/setup_term.bat -OutFile $env:TEMP\setup_term.bat; & $env:TEMP\setup_term.bat
```

It checks for Git and Python 3.10 or later (and offers to install them with winget), asks for an
install folder (default `%USERPROFILE%\aether-term`), clones the repository, installs PyQt6,
cryptography and certifi, and puts an **AETHER TERM** shortcut on the desktop.

**From source.** In a clone of the repository:

```bash
pip install -r requirements.txt
python src/main.py
```

On Windows you can also double-click `start_aether_term.bat`. It finds Python, checks the
required packages and offers to install them, and offers the optional `keyring` and `pywin32`
packages. `pywin32` is needed only for OmniRig PTT.

To build the installer or portable zip yourself, see [BUILD_GUIDE.md](BUILD_GUIDE.md).

### 2.2 Where Aether Term keeps its files

| What | Windows | Linux |
|---|---|---|
| Settings (`settings.json`) | `%APPDATA%\Aether Term\` | `~/.config/Aether Term/` |
| Saved BBS passwords (`passwords.enc`) | `%APPDATA%\Aether Term\` | `~/.config/Aether Term/` |
| Hamlib downloaded by Aether Term | `%APPDATA%\Aether Term\hamlib\` | `~/.config/Aether Term/hamlib/` |
| Program log (`aether-term.log`) | `%USERPROFILE%\Aether Term\logs\` | `~/Aether Term/logs/` |
| Session logs | same `logs` folder | same `logs` folder |

The program log rotates at 2 MB and keeps 5 old copies. Settings and passwords are written
through a temporary file and then renamed, so a crash mid-save leaves the old file intact.

### 2.3 Coming from VARA Term

The first time Aether Term starts, if `%APPDATA%\Aether Term\` does not exist yet and
`%APPDATA%\VARA Term\` does, the old folder is copied across: settings, saved station passwords
and the downloaded Hamlib. The old folder is left alone, so VARA Term still works. Logs are now
written to `%USERPROFILE%\Aether Term\logs\`. Details are in the
[README](../README.md#upgrading-from-vara-term).

### 2.4 Updates

At startup Aether Term checks for a newer version in the background. How it updates depends on
how it was installed:

| Install | How a newer version is found | What the update dialog offers |
|---|---|---|
| Installer | Latest GitHub release is newer than the running version | **Download & Install**: downloads the setup program, checks its size and the SHA-256 digest GitHub publishes, closes Aether Term and runs setup silently. The new version starts when setup finishes. |
| Portable zip | Same as above | **Open Download Page** |
| Git install (one-line installer or a clone) | New commits on `origin/main` that your copy does not have | **Update & Restart**: pulls the new commits and restarts Aether Term |

Every update dialog also has **Later** and **Skip This Version**. Settings and saved passwords
are kept by all three methods.

- The startup prompt never appears during a session, and not for a version you skipped.
- When an update is available, the status bar shows **UPDATE vX.Y.Z** (installer and portable)
  or **UPDATE (n)** with the number of new commits (git). Click it to open the dialog.
- **Help → Check for Updates...** checks by hand. It shows a skipped version too, and says
  "Aether Term X.Y.Z is the latest version" when there is nothing new.
- Turn the startup check off with **Settings → Terminal Setup → Check for updates at startup**.
- For git installs, local changes to the files are stashed before the pull and put back
  afterwards, also when the pull fails. The update needs `git` on the PATH.

---

## 3. First start

1. **Set your callsign.** Open **Settings → Terminal Setup...**, enter **My Callsign** and, if you
   use one, an **SSID** (0 to 15; 0 means no SSID). Click **OK**. Until a callsign is set, the
   welcome text says "No callsign configured", and pressing Connect opens the settings.
2. **Choose a mode** in the mode dropdown on the second toolbar row (VARA FM, VARA HF, Aether HF,
   Soundmodem, KISS TNC or Local test), or in **Settings → Terminal Setup → Modem**.
3. **Check the modem program path** under **Settings → Modem Configuration...** if you want Aether
   Term to start the modem for you (next section).
4. **Save the BBS password** under **Settings → Security / Passwords...** if the BBS uses
   automatic login (see [section 6](#6-logging-in-to-the-bbs)).
5. Type the BBS callsign in **Target** and press **Connect**.

### 3.1 Starting the modem program automatically

Half a second after Aether Term opens, and whenever you switch modes, it can start the modem
program for the selected mode. When you switch modes or close Aether Term, the modem program it
started is closed. On Windows it is ended with `taskkill /F /T`, which also ends any child
processes.

| Mode | Setting | Default | Where it looks |
|---|---|---|---|
| VARA FM | Start VARA FM with Aether Term (and close on exit) | On | The path you set (default `C:\VARA FM\VARAFM.exe`), then `C:\VARA FM\VARA FM.exe`, `C:\Program Files\VARA FM\VARAFM.exe`, `C:\Program Files (x86)\VARA FM\VARAFM.exe` |
| VARA HF | Start VARA HF with Aether Term (and close on exit) | On | The path you set (default `C:\VARA HF\VARA HF.exe`), then `C:\VARA\VARA.exe`, `C:\Program Files\VARA\VARA.exe`, `C:\Program Files (x86)\VARA\VARA.exe` |
| Aether HF | Start Aether HF with Aether Term (and close on exit) | Off | The path you set, else `%LOCALAPPDATA%\Aether HF\aether-hf.exe`. Not started if Aether HF's control API already answers ("Aether HF is already running — not starting another"). |
| Soundmodem | Auto-launch Soundmodem | Off | Only the **Exe Path** you set. There is no default location. |
| KISS TNC | (none) | | No modem program is used. |
| Local test | (none) | | No modem program is used. |

If the program is found somewhere other than the configured path, that path is saved. If it is
not found, the terminal says "*&lt;mode&gt;* modem not found. Set the executable path in Settings >
Modem Configuration."

Only programs Aether Term started itself are closed. A modem you started by hand keeps running.

---

## 4. The main window

From top to bottom: the menu bar, a two-row connection bar, the terminal, the command line, the
macro bar, the S/N graph, and the status bar.

### 4.1 Menus

| Menu | Item | What it does |
|---|---|---|
| File | Connect (Ctrl+Shift+C) | Same as the Connect button; unavailable while a call is under way |
| | Disconnect | Same as the Disconnect button |
| | Exit (Ctrl+Q) | Closes Aether Term (and any modem program it started) |
| Settings | Terminal Setup... | Settings, Terminal Setup tab |
| | Modem Configuration... | Settings, Modem Configuration tab |
| | Security / Passwords... | The Password Manager (saved BBS passwords) |
| | Connection Profiles... | The profile manager |
| Aether HF | Modem Status... | Asks Aether HF for its status and shows it (version, state, callsign, bandwidth, rung, host port, keying, rules, channel, and anything that needs attention) |
| | Open Station Panel in Browser | Opens Aether HF's control address (`http://<host>:8515/`) in your browser |
| | Host Program Setup Guide | Aether HF's guide to host programs, on GitHub |
| | Download Aether HF | Aether HF's Releases page |
| Help | About Aether Term | Version and credits |
| | BBS Commands Reference | A short list of common Aether BBS commands (messages, bulletins, files, Winlink, other) |
| | Check for Updates... | See [Updates](#24-updates) |

### 4.2 Connection bar, row 1

- **Target** — the BBS callsign to call, for example `KK4ODA-5`. It is an editable dropdown of the
  last 20 stations you called, most recent first. Text is converted to upper case.
- **Via 1 / Via 2** — digipeaters for the path. Each offers **None** plus the last 10 digipeaters
  you used, and you can type a new one. The last call's choice (None included) comes back the
  next time Aether Term starts. Digipeaters work with VARA FM, Soundmodem and a KISS TNC only.
  See [Digipeaters](#52-digipeaters-vara-fm-soundmodem-and-kiss-tnc).
- **Connect** — starts the connection. Enabled only while disconnected.
- **Disconnect** — ends the session, or stops a connection that is still being set up.
- **Clear** — clears the terminal window. It does not affect the session or the session log.

Target, Via 1 and Via 2 are locked while a connection is under way.

### 4.3 Connection bar, row 2

- **Mode dropdown** — VARA FM, VARA HF, Aether HF, Soundmodem, KISS TNC, Local test. Changing it closes
  the old modem's link and program and starts the new one if its auto-launch setting is on.
  It is locked while connected or connecting; trying to switch then prints "Disconnect before
  switching to ...".
- **Status dot** — red when disconnected, yellow while the modem link is up or a call is in
  progress, green when connected.
- **Profile dropdown** — **(none)** or one of your saved profiles. Picking one fills in the
  operator, target, path, mode and bandwidth (see [Profiles](#71-connection-profiles)). Locked
  during a call.

### 4.4 Terminal and command line

The terminal shows everything the BBS sends, plus Aether Term's own messages in colour:

| Colour | Meaning |
|---|---|
| Cyan | Aether Term status messages ("Connecting to ...", "Switched to ...") |
| Green | Success ("*** CONNECTED to ... ***", "[AUTH] Authentication successful ✓") |
| Yellow | Warnings ("*** DISCONNECTED ***", tips) |
| Red | Errors |
| Dim grey | What you sent (`> L`), and PTT events if you turned them on |

Lines are not wrapped, so text art from the BBS keeps its shape; scroll sideways if a line is
too long. Right-click the terminal for **Copy**, **Select All** and **Clear Screen**.

The command line below the terminal is active only while connected. Type a command and press
Enter. What you typed is echoed in dim grey as `> command`. See also
[Keyboard and command line](#11-keyboard-and-command-line).

A prompt the BBS leaves without a line end (such as `>` or `4 Back:`) is shown at once if it is
short and ends in `>` or `:`, otherwise after the BBS has been quiet for one second. When the
rest of the line arrives, it continues on the same screen line.

### 4.5 Macro bar

The **Quick:** bar under the command line holds up to 8 macro buttons. Clicking one sends its
command as if you had typed it. The defaults are:

| Button | Sends |
|---|---|
| Help | `H` |
| List Mine | `L` |
| Read New | `N` |
| List Bull | `LB` |
| List Files | `FL` |
| Bye | `B` |

Change them under **Settings → Macros**. A macro clicked while not connected prints "Not
connected — command not sent."

### 4.6 S/N graph

The strip under the macro bar plots the last 60 S/N reports from the modem during a session.
It is cleared when the session ends. Only the VARA-protocol modems (VARA FM, VARA HF, Aether HF)
report S/N; Soundmodem and Local test do not.

### 4.7 Status bar

From left to right:

| Field | What it shows |
|---|---|
| State | `DISCONNECTED` (red), `MODEM READY`, `INITIALIZING`, `CONNECTING...`, `DISCONNECTING...` (yellow), `CONNECTED` (green) |
| S/N | Last S/N from the modem, for example `S/N: 12 dB` |
| BW | Bandwidth. Before a call: the HF bandwidth for VARA HF and Aether HF (`BW: 500 Hz`), the FM bandwidth setting for VARA FM (`BW: WIDE`), `—` for Soundmodem, KISS TNC and Local test. During a call, the value the modem reports with `CONNECTED`, if it reports one. |
| Speed | Link speed from the modem's `BITRATE` report, for example `Speed: 1234 bps (mode 9)` |
| Duration | Length of the current session |
| Modem | `Modem: Not connected`, `Modem: Connected`, `Modem: Error`, or the modem's version (Aether HF answers `VERSION`). In KISS TNC mode it shows the TNC link, for example `TNC: COM5` or `TNC: not connected`. In Local test mode this field shows the BBS: see [Local test](#56-local-test-no-radio). |
| BBS link | `BBS link: <type>`: the link type the Aether BBS reports for this session (`;TRANSPORT`) |
| Aether | Aether HF mode only. See [Aether HF](#54-aether-hf). Click it for the full status. |
| TX | `● TX` in red while Aether Term is keying the radio (VARA HF, or Aether HF with host-program keying). Not shown with *None (VOX)* or when the modem keys the radio itself. |
| UPDATE | Shown when an update is available. Click it. |
| CHAT | `CHAT: <room>` while you are in a chat room on the BBS |

The window title shows the callsign you connect as, for example `Aether Term — KK4ABC-7`. In
Local test mode it reads `Aether Term — LOCAL TEST — not on the air as <call>`.

---

## 5. Connecting

### 5.1 What happens when you press Connect

1. Aether Term checks that a callsign is set and a target is entered, and that the Via fields
   are valid for the mode.
2. In Aether HF mode, it first asks the modem whether it can take the call (preflight).
3. If this program keys the radio (VARA HF, or Aether HF set to host-program keying) and the PTT
   method is not *None (VOX)*, it connects to OmniRig, rigctld or FLrig. If that fails, the call
   stops here.
4. It opens the TCP link to the modem. VARA and Aether HF are tried up to **Max Retries** times
   (default 5), 2 seconds apart, so a modem that is still starting has time to come up.
5. It sets up the modem: `DISCONNECT` (clears any leftover call), `MYCALL <your call>`,
   `COMPRESSION OFF`, then `BW500`/`BW2300`/`BW2750` for HF modes, `P2P SESSION` or
   `WINLINK SESSION` for VARA HF, and `VERSION` for Aether HF.
6. It sends `CONNECT <your call> <target>` (with `VIA ...` for digipeaters).
7. When the modem reports `CONNECTED`, the terminal shows `*** CONNECTED to <call> ***`, the
   command line is enabled, the duration timer and session log start, and the target is added to
   the history.

A call that fails returns the state to `DISCONNECTED` and prints "Connection to *&lt;target&gt;*
failed — closing the modem link." The modem link is closed after every session.

Pressing **Disconnect** during a session sends `DISCONNECT` to the modem and waits for it to
report the end of the link. With VARA HF the radio stays keyable until then, so the other
station hears the disconnect frames.

### 5.2 Digipeaters (VARA FM, Soundmodem and KISS TNC)

Enter digipeaters in **Via 1** and **Via 2**:

- At most 2 digipeaters in total. A field may also hold two calls separated by a space or comma
  (`W1AW-5,K1ABC`).
- Each call is 3 to 7 letters and digits, with an optional SSID of -1 to -15, -T or -R.
- Choose **None** in both boxes for a direct connection.

Digipeaters are refused in VARA HF, Aether HF and Local test modes with the message "Digipeaters
are supported with VARA FM, Soundmodem and a KISS TNC." Set both boxes to None or switch modes.

**VARA FM needs a registered VARA license to connect through digipeaters.** Aether Term reminds
you of this when you call through a digipeater. If VARA reports `LINK UNREGISTERED` on such a
call, Aether Term says that VARA FM requires a license for digipeaters.

With Soundmodem the path is sent with each call (AGWPE "connect via" frame). Soundmodem's own
Digi settings are for Soundmodem acting as a digipeater, not for the path of your calls.

With a KISS TNC, Aether Term puts the path in every frame itself and waits longer for answers
(the retry time is multiplied by 2 × digipeaters + 1).

### 5.3 VARA FM and VARA HF

Start VARA (or let Aether Term start it) and make sure its TCP command port matches **Settings →
Modem Configuration → VARA FM Modem / VARA HF Modem → Command Port** (default 8300). The data
port is always the command port + 1.

**VARA FM** keys the radio itself. The **FM Bandwidth** setting (NARROW/WIDE) is shown in the
status bar and stored in profiles. VARA FM has no host command for it, so set the real bandwidth
in VARA FM's own setup (FM System) to match.

**VARA HF** settings, in **Settings → Terminal Setup → HF Settings**:

- **Session Bandwidth (Hz)**: 500 (default), 2300 or 2750. Sent as `BW500`, `BW2300` or `BW2750`.
- **Session Type**: *P2P (BBS or station)* (default) sends `P2P SESSION`, the retry cycle VARA
  specifies for calls to a BBS or another station. *Winlink gateway* sends `WINLINK SESSION`,
  VARA's 4-second cycle for RMS gateways.

**VARA HF needs the host to key the radio.** Choose how in **Settings → Modem Configuration → HF
PTT Control → HF PTT Method**:

| Method | What you need | Settings shown |
|---|---|---|
| None (VOX) | The radio keys itself on audio (VOX, or an interface that keys on audio) | none |
| OmniRig (default) | OmniRig installed and set up for your radio; `pywin32` (included in the Windows builds; `pip install pywin32` for a source install) | OmniRig Rig Number (1 or 2) |
| Hamlib (rigctld) | rigctld already running, or Aether Term starts it | Hamlib panel (below) |
| FLrig | FLrig running with its XML-RPC server | FLrig Host (127.0.0.1), FLrig Port (12345) |

Aether Term connects to the PTT method when you press Connect, before it opens the modem link.
**If it cannot reach the radio, the call is not sent.** The terminal says "Connect stopped:
*&lt;method&gt;* PTT can't key the radio" and a **PTT Unavailable** dialog gives the reason, for
example "Cannot connect to FLrig at http://127.0.0.1:12345. Is FLrig running?" Start the program,
choose another method, or choose *None (VOX)* if the radio keys itself on audio.

Once connected, Aether Term keys the radio on each `PTT ON` from VARA and unkeys on `PTT OFF`, in
the order VARA sent them. Safety releases:

- If no `PTT OFF` arrives within 90 seconds of keying, the radio is unkeyed and the terminal shows
  "[PTT] PTT watchdog: forced release after timeout".
- Whenever the modem link closes (session over, call failed, VARA crashed), the radio is unkeyed
  and the rig link is closed.

**Hamlib panel** (shown when the method is *Hamlib (rigctld)*):

| Field | Default | Notes |
|---|---|---|
| Rig Model | Hamlib Dummy (test) [1] | Choose your radio. Type to search. The Dummy model keys no radio, so Connect stops with "Hamlib is set to its Dummy rig, which keys no radio" until you choose yours. |
| Serial Port | (empty) | CAT port, for example `COM3` |
| Serial Speed | Auto | Auto, 4800 to 115200 |
| rigctld Host | 127.0.0.1 | |
| rigctld Port | 4532 | |
| Auto-launch rigctld with Aether Term | On | Aether Term starts rigctld with `-T <host> -t <port> -m <model> [-r <port>] [-s <speed>]` plus Extra Args when you press Connect, and stops it at the end |
| rigctld Path | (empty) | Empty: Aether Term's own download (`%APPDATA%\Aether Term\hamlib\bin\rigctld.exe`), a `hamlib` folder next to the program, `Program Files\Hamlib*`, `%LOCALAPPDATA%\Hamlib`, then the PATH |
| Extra Args | (empty) | Extra rigctld options, for example `--set-conf=rts_state=ON` |
| Download / Update Hamlib... | | Checks the latest Hamlib release on GitHub, then downloads and installs it into `%APPDATA%\Aether Term\hamlib\` and fills in the rigctld path |

If rigctld exits as soon as it starts (wrong model, port or serial device), the PTT Unavailable
dialog shows rigctld's own message.

**OmniRig note:** Aether Term waits up to 5 seconds for OmniRig to report the radio online. If
OmniRig is running but the radio does not answer in that time, only the program log notes it and
the call goes ahead. Check OmniRig's rig type, COM port and baud rate if the radio does not key.

### 5.4 Aether HF

Aether HF is an open-source HF modem. Aether Term talks to it over its VARA-compatible host port
and reads its status from its control API. **On the air, Aether HF talks only to other Aether HF
stations**, on the same bandwidth and link-protocol version.

Setup is in the [README](../README.md#using-aether-hf) and the protocol details in
[AETHER_HF.md](AETHER_HF.md). In short:

1. In Aether HF, choose your rules (Setup step 1), decide how the radio is keyed (step 2), and
   turn on **Host programs** (step 5). The host port is off by default.
2. In Aether Term, choose **Aether HF** in the toolbar and set the **Bandwidth** in **Settings →
   Terminal Setup → Aether HF Settings**: 2300 Hz (default) or 500 Hz. Both stations must use
   the same one.
3. **Settings → Modem Configuration → Aether HF Modem → Test Aether HF** asks the modem for its
   status. "Host port on, rules set, keying and sound card OK." means it is ready.

**Keying.** Normally Aether HF keys the radio itself and Aether Term does not key anything.
Only if Aether HF's Setup step 2 is *host program*, tick **Aether HF keying is "host program" —
key the radio here**; Aether Term then keys the radio with the HF PTT method, exactly as for VARA
HF, including the Connect-stops rule above.

**Status bar.** While Aether HF is the selected mode, Aether Term asks its control API for status
every 2 seconds. The field reads `Aether <version> · <bandwidth> Hz`, then the state when it is
not idle, the rung name while connected, and `TX BLOCKED` or `FAULT` when something is wrong. It
is grey when the modem cannot be reached (`Aether: offline`), red when something stops it
transmitting, yellow while transmitting, and green otherwise. Click it for the full status.

**Preflight.** On Connect, the terminal shows "[AETHER] Checking the modem..." and then the
modem's status line. The call is not sent if:

- the host interface is off,
- no rules are chosen, or Aether HF's regulatory profile would not load,
- the rules block transmitting at the current dial,
- there is a keying fault or a sound card fault.

Each reason is printed in red, followed by "[AETHER] Not connecting. Fix the above in Aether HF
and try again." If the control API cannot be reached at all, Aether Term warns and connects over
the host port without the checks.

**After connecting to the port**, Aether Term checks the modem's `VERSION` answer. If it is not
Aether HF (for example VARA HF left running on port 8300), it warns: "The modem on this port
reports ..., not Aether HF."

**A call that ends with no session**: Aether Term asks the modem why. If the modem reports a
problem, it is printed; otherwise the terminal reminds you that Aether HF talks only to other
Aether HF stations, and that Aether HF's Log tab has the reason for every refused call.

### 5.5 Soundmodem (AGWPE)

For AX.25 packet through Soundmodem, Direwolf or any AGWPE-compatible TNC. Set **Settings → Modem
Configuration → Soundmodem (AGWPE) → Host** (default 127.0.0.1) and **AGWPE Port** (default
8000), and make sure the AGWPE server is enabled in the TNC. Aether Term uses the TNC's first
radio port.

- The TNC keys the radio. Aether Term's PTT settings are not used.
- Aether Term makes one attempt to reach the TNC; **Max Retries** does not apply.
- Digipeaters work (see [5.2](#52-digipeaters-vara-fm-soundmodem-and-kiss-tnc)).
- **An unanswered call is cancelled after 60 seconds**: Aether Term tells the TNC to stop calling
  and prints "No answer from *&lt;target&gt;* in 60 s — call cancelled". Disconnect while calling
  also cancels the call.
- If Soundmodem quits or crashes, the session ends with "Lost connection to Soundmodem".
- Every AGWPE frame sent and received is written to the program log, which helps when a session
  connects but no data seems to pass.

### 5.6 Local test (no radio)

Local test lets you try an Aether BBS on the same PC without a radio or modem. Aether Term plays
the VARA FM modem: it listens on 127.0.0.1 only (never reachable from another machine), on
command port 8500 and data port 8501 by default. Those are not VARA's 8300/8301, so a real VARA
can keep running. **Nothing is transmitted.** The session runs through the same code as on the
air (`;TRANSPORT?`, automatic login and the rest), so what you see is what a station on the air
gets.

**Setting it up:**

1. **Start Aether Term first** and choose **Local test** in the toolbar (or **Settings → Terminal
   Setup → Modem → Local test (no radio)**). The terminal says "[LOCAL TEST] No radio: nothing is
   transmitted." The status bar shows `Local test: waiting for the BBS on 8500/8501` and the title
   bar says `LOCAL TEST — not on the air`.
2. In **Aether BBS**, open **Settings → Instances** and add an instance:

   | Field | Value |
   |---|---|
   | Name | Local test |
   | Transport | VARA FM |
   | Cmd port | 8500 |
   | Data port | 8501 |
   | Auto Start | off |

   Save, then start or enable the instance. The BBS tries to reach the modem 5 times over about
   15 seconds and then gives up. If Aether Term was not ready, start the instance again from the
   BBS dashboard.
3. When the BBS attaches and sends its callsign, Aether Term's status bar shows
   `Local test: <BBS call> attached on 8500/8501` and the terminal shows the same line.
4. Press **Connect**. **Aether Term always calls the BBS that attached**, whatever the Target box
   says; if they differ it prints "Local test: calling *&lt;call&gt;*, the BBS attached here" and
   puts that call in the Target box. The BBS's saved password is used as usual.

**Who you connect as.** **Settings → Modem Configuration → Local test → Connect as** sets the
callsign used in Local test mode. Leave it empty to use your own callsign (or the active
profile's). Set it to, for example, your sysop call, or a stranger's call such as `N0CALL`, to
see what an unknown station gets. It also decides which saved password is looked up (see
[6.2](#62-saving-passwords)).

Other points:

- **Cmd Port** and **Data Port** (1024 to 65535) can be changed in the same panel. They must match
  the BBS instance. If the two are set the same, the data port is moved by one when you click OK.
- Disconnect ends the session; the BBS stays attached for the next call. If the BBS instance is
  stopped, the status bar shows `Local test: BBS detached — waiting for it on 8500/8501`.
- Digipeaters, PTT and the modem auto-launch do not apply.
- Connection profiles have no Local test mode. Choosing a profile switches to the profile's mode.

### 5.7 KISS TNC

KISS TNC mode talks straight to a TNC with no Soundmodem or other program in between: the TNC
built into a radio such as the Kenwood TH-D74 or TH-D75, a Bluetooth LE radio or TNC
(Vero VR-N76 / VR-N7600, Mobilinkd), a hardware TNC, or Direwolf. It works like EasyTerm or
VARA Terminal's KISS mode. Aether Term runs the AX.25 connection itself (calls, numbered frames,
acknowledgements, retries, digipeater paths); the TNC only sends and receives packets.

Choose **KISS TNC** in the toolbar, then set **Settings → Modem Configuration → KISS TNC → Connect
via**:

- **Bluetooth or USB serial port (COM)** — for a radio paired over Bluetooth Classic or plugged
  in with USB, and for serial TNCs. Pick the port and click **Refresh** if it is missing.
  - *Kenwood TH-D74 / TH-D75 over Bluetooth:* pair the radio in Windows Bluetooth settings. Windows
    creates two COM ports; use the outgoing one, named *Standard Serial over Bluetooth link*. On
    the radio, switch the built-in TNC to **KISS** mode and choose its band and speed (1200 or
    9600 baud on the air). The baud rate setting in Aether Term does not matter for Bluetooth.
  - *Over USB:* install the radio's USB driver, pick its COM port, and set the baud rate the
    radio's manual gives for the TNC.
- **Bluetooth Low Energy (BLE)** — for radios and TNCs that offer KISS over BLE (VR-N76,
  VR-N7600, UV-Pro, Mobilinkd TNC3/TNC4 and similar). Turn on the radio's KISS TNC, press
  **Scan** and pick the radio; devices that advertise the KISS service are listed first. The
  **BLE service** field holds the service UUID; leave it empty for the usual KISS-over-BLE
  service (`00000001-ba2a-46c9-ae49-01b0961f68bb`). *BLE support is new and has not yet been
  tested with these radios.*
- **TCP** — for Direwolf (port 8001) or a network TNC.

When you press Connect, Aether Term opens the link to the TNC (the status bar shows
`TNC: COM5`, `TNC: BLE <address>` or `TNC: 127.0.0.1:8001`), sends the TNC its settings if
**Send TXDELAY, persistence and slot time** is on, and calls the target. Disconnect ends the call
and closes the link to the TNC, so the radio is free for other programs between sessions.

Other points:

- **TNC port** is 0 for radios and single-port TNCs.
- **Init commands** are for TNC2-style TNCs that must be told to enter KISS mode, for example
  `KISS ON\rRESTART`. Leave the field empty for radios; they are set to KISS from their menus.
- **Packet length**, **Window (MAXFRAME)**, **Retry time (FRACK)** and **Retries** are the usual
  AX.25 settings. The defaults (128, 4, 7 s, 10) suit 1200 baud. On a busy channel or a weak
  link, a smaller window and packet length help.
- Digipeaters work (see [5.2](#52-digipeaters-vara-fm-soundmodem-and-kiss-tnc)).
- A call that gets no answer ends with "TNC: no answer from *&lt;target&gt;* after *N* tries". If the
  other station stops answering during a session, the session ends with "TNC: link lost".
- Every AX.25 frame sent and received is written to the program log.
- Profiles can use KISS TNC mode. PTT, bandwidth and the modem auto-launch do not apply.

---

## 6. Logging in to the BBS

### 6.1 Automatic login (HMAC-SHA256)

The Aether BBS can ask for a password with a challenge instead of a plain password prompt.
Aether Term handles it like this:

1. The BBS sends `;AUTH HMAC-SHA256 <nonce>`, a random 32-digit hex number.
2. Aether Term looks up the saved password for this station and operator (next section).
3. It computes HMAC-SHA256 of the nonce with the password as the key, waits 1.5 seconds (time for
   a half-duplex link to turn around), and sends `;AUTH <64-digit hex answer>`.
4. The BBS answers `;AUTH OK` or `;AUTH FAIL`.

The password itself is never sent. On screen you see:

```
[AUTH] Challenge received — responding automatically...
[AUTH] Authentication successful ✓
```

The protocol lines and the BBS's "Enter password:" prompt are hidden while this happens. To see
the raw lines, tick **Settings → Security → Show auth protocol messages in terminal (debug)**.
To stop automatic answers, untick **Auto-respond to HMAC challenges**. The terminal then shows
"[AUTH] Automatic login is off (Settings → Security) — manual auth required" and the BBS's
password prompt, and you type the answer yourself.

If the BBS rejects the answer, the terminal shows "[AUTH] Authentication FAILED ✗ — check saved
password" in red.

After a successful login, Aether Term records the time in the password's **Last Used** column and,
if a tactical address is configured, sends it (see [9.2](#92-tactical-address)).

### 6.2 Saving passwords

Open **Settings → Security / Passwords...**. The **Password Manager** lists each saved password
with its **Operator**, **Target**, a masked **Password**, **Auth Mode** (always HMAC-SHA256) and
**Last Used**. Use **Add**, **Edit** and **Remove**.

In the Add Password window:

- **Operator** — the callsign you connect as. It is filled in with the callsign currently in use
  (profile or Local test callsign included). **Leave it blank** for a password any operator on
  this PC can use; it shows as `(any)` in the list.
- **Target BBS** — the station's callsign. It cannot be changed when editing; remove the entry
  and add a new one instead.
- **Password** — tick **Show password** to see what you typed.

**Which password is used.** When connecting as operator `KK4ABC-7` to target `KK4ODA-5`, Aether
Term tries, in this order, and uses the first one it finds:

| Order | Operator | Target |
|---|---|---|
| 1 | KK4ABC-7 | KK4ODA-5, then KK4ODA |
| 2 | KK4ABC | KK4ODA-5, then KK4ODA |
| 3 | KK4ABC with any other SSID | KK4ODA-5, then KK4ODA |
| 4 | (blank) | KK4ODA |
| 5 | (blank) | KK4ODA-5 |

Things to know:

- **The target's SSID is optional.** On the Aether BBS a password belongs to the base callsign,
  so saving the target as `KK4ODA` covers `KK4ODA-5`, `KK4ODA-10` and so on.
- **The operator's SSID is optional too.** The BBS knows you by your base callsign, so a password
  saved for operator `KK4ABC-7` is also used when you connect as `KK4ABC` or `KK4ABC-2`. An entry
  for your exact callsign, SSID included, wins over one for another SSID.
- With a profile, the profile's callsign is the operator. In Local test mode, the **Connect as**
  callsign is.

**Storage.** Passwords are kept in `passwords.enc` in the settings folder (see
[2.2](#22-where-aether-term-keeps-its-files)), encrypted with Fernet. The encryption key comes
from a passphrase built into the program, which is kept in the Windows Credential Manager when
the optional `keyring` package is installed. The encryption keeps the passwords from being read
casually; anyone with the file and the program can still decrypt it, so protect the file like any
saved password. If the `cryptography` package is missing, the file is plain JSON.

### 6.3 No saved password

If the BBS sends a challenge and no password matches, the terminal shows:

```
[AUTH] No saved password — manual auth required
;AUTH HMAC-SHA256 ...
  (No password saved for station KK4ODA-5 with operator KK4ABC or blank. Add one in
  Settings → Security / Passwords to log in automatically.)
```

The station and operator named there are the ones Aether Term looked for, so compare them with
the Password Manager.

You can then answer the BBS's prompt by typing. What you type until the BBS answers `;AUTH OK` or
`;AUTH FAIL` is shown as `********` on screen and in the session log. **It is still sent as typed,
in the clear, over the air.** Save the password instead whenever you can.

### 6.4 Winlink registration (WLREG)

The Aether BBS can check Winlink mail for you. To register, the BBS needs your Winlink password,
and Aether Term sends it encrypted:

1. Start registration on the BBS (the `WLREG` command).
2. The BBS sends a challenge (`;WLREG NONCE <nonce>`). The terminal shows "[WLREG] Winlink
   registration challenge received".
3. A **Winlink Registration** window asks for your Winlink password. It is typed on your PC, not
   over the air.
4. Aether Term encrypts it with a key made from your saved BBS password and the nonce, sends it as
   `;WLREG <hex>`, and prints "[WLREG] Encrypted Winlink password sent".

A saved BBS password is required. Without one, Aether Term prints "[WLREG] No BBS password saved
— cannot encrypt Winlink password" and sends `CANCEL`. Cancelling the window, or leaving it empty,
also sends `CANCEL` ("[WLREG] Registration cancelled").

---

## 7. Profiles, macros, history and session logs

### 7.1 Connection profiles

A profile stores a whole connection setup. Manage them in **Settings → Connection Profiles...**:

| Field | Notes |
|---|---|
| Profile Name | Shown in the profile manager list |
| My Callsign / My SSID | The operator for this profile. Blank: your global callsign from Settings. |
| Tactical Address | Optional. Sent as `;TACTICAL <address>` after login (see [9.2](#92-tactical-address)). |
| Target Callsign | The BBS to call. Required to connect from the profile. |
| Mode | VARA FM, VARA HF, Aether HF, Soundmodem (AGWPE) or KISS TNC |
| FM Bandwidth | WIDE (default) or NARROW, for VARA FM profiles |
| HF Bandwidth | 500, 2300 or 2750. Aether HF uses 500 or 2300 (2750 runs as 2300). |
| Via 1 / Via 2 | Digipeaters, for VARA FM, Soundmodem and KISS TNC profiles |

- **Add** creates "New Profile" and saves it at once. Fill in the fields and click **Save
  Changes**.
- **Remove** deletes the selected profile.
- **Connect to This Profile** uses the fields as they are on screen (saved or not), closes the
  window and connects. If the profile switches to a mode whose modem program Aether Term starts,
  it waits 5 seconds for the program before calling.

In the main window, the **Profile** dropdown lists profiles as
`<n>: <operator> → <target> | <mode>/<bandwidth> | [<tactical>]`. Choosing one switches the mode
if needed (closing the old modem program and starting the new one), then sets the operator,
target, Via boxes and bandwidth. The window title shows the profile's callsign. Choosing
**(none)** goes back to your global callsign; the bandwidth stays as the profile set it.

### 7.2 Macros

**Settings → Macros** has 8 rows, each with a label and a command. A row is kept only if both are
filled in. The buttons appear on the **Quick:** bar in the order of the rows. Emptying every row
removes all buttons.

### 7.3 Target and digipeater history

- Every station you call is put at the top of the **Target** dropdown, up to 20. The callsign the
  modem reports when connected is added too, if it differs.
- Digipeaters you use are added to both Via dropdowns, up to 10, most recent first.
- The welcome text at startup lists your recent stations.

### 7.4 Session logs

With **Settings → Terminal Setup → Enable session logging** on (the default), each session is
written to its own file in the logs folder (see [2.2](#22-where-aether-term-keeps-its-files)),
named `YYYY-MM-DD_HHMMSS_<remote call>.log`. It starts with the date, your callsign, the remote
call and the mode, then every line received and sent with a time stamp, and ends with the time
the session ended. Passwords typed during a manual login are logged as `********`.

---

## 8. Settings reference

Open with **Settings → Terminal Setup...** or **Settings → Modem Configuration...**. The dialog has
four tabs. Changes take effect when you click **OK**; **Cancel** discards them. Hover over a field
for its tooltip.

### 8.1 Terminal Setup

| Group | Setting | Default | Notes |
|---|---|---|---|
| Station Identity | My Callsign | (empty) | Up to 10 characters, saved in upper case |
| | SSID | 0 | 0 to 15; 0 means none |
| Modem | VARA FM / VARA HF / Aether HF / Soundmodem (AGWPE) / KISS TNC / Local test (no radio) | VARA FM | Same as the toolbar mode dropdown. Greyed out during a call. |
| HF Settings (VARA HF only) | Session Bandwidth (Hz) | 500 | 500, 2300, 2750 |
| | Session Type | P2P (BBS or station) | Or *Winlink gateway* |
| Aether HF Settings (Aether HF only) | Bandwidth (Hz) | 2300 | 2300 or 500; both stations must match |
| FM Settings (VARA FM only) | FM Bandwidth | WIDE | NARROW or WIDE. Shown in the status bar; set the real bandwidth in VARA FM. |
| Appearance | Font | Consolas | Consolas, Courier New, Lucida Console, DejaVu Sans Mono, Liberation Mono. If the font is missing, another monospaced font is used. |
| | Font Size | 11 | 8 to 24; applies to the terminal and the command line |
| Connection | Max Retries | 5 | 1 to 20. Attempts to reach the VARA or Aether HF modem's TCP ports, 2 s apart |
| | Enable session logging | On | See [7.4](#74-session-logs) |
| | Show PTT ON/OFF events in terminal | Off | Prints the modem's `PTT ON` / `PTT OFF` lines in dim grey |
| | Check for updates at startup | On | See [2.4](#24-updates) |

### 8.2 Modem Configuration

All groups are shown, but only the selected mode's group can be edited. To change another mode's
settings, select that mode under **Terminal Setup → Modem** first. In every VARA-style group the **Data
Port** is read-only and always the command port + 1.

**VARA FM Modem**

| Setting | Default |
|---|---|
| Host | 127.0.0.1 |
| Command Port | 8300 |
| Data Port | 8301 |
| Start VARA FM with Aether Term (and close on exit) | On |
| Executable | `C:\VARA FM\VARAFM.exe` (with **Browse...**) |

**VARA HF Modem**

| Setting | Default |
|---|---|
| Host | 127.0.0.1 |
| Command Port | 8300 |
| Data Port | 8301 |
| Start VARA HF with Aether Term (and close on exit) | On |
| Executable | `C:\VARA HF\VARA HF.exe` (with **Browse...**) |

**Aether HF Modem**

| Setting | Default | Notes |
|---|---|---|
| Host | 127.0.0.1 | Also used for the control API |
| Command Port | 8300 | Aether HF's host-program port |
| Data Port | 8301 | |
| Control API Port | 8515 | Read-only status, rules and faults |
| Aether HF keying is "host program" — key the radio here | Off | See [5.4](#54-aether-hf) |
| Start Aether HF with Aether Term (and close on exit) | Off | |
| Executable | (empty) | Empty: `%LOCALAPPDATA%\Aether HF\aether-hf.exe` |
| Test Aether HF | | Asks the control API for status and shows the result below the button |

**HF PTT Control** (editable in VARA HF and Aether HF modes)

| Setting | Default | Shown for |
|---|---|---|
| HF PTT Method | OmniRig | always: None (VOX), OmniRig, Hamlib (rigctld), FLrig |
| OmniRig Rig Number | 1 | OmniRig |
| FLrig Host | 127.0.0.1 | FLrig |
| FLrig Port | 12345 | FLrig |
| Hamlib (rigctld) panel | see [5.3](#53-vara-fm-and-vara-hf) | Hamlib (rigctld) |

**Soundmodem (AGWPE)**

| Setting | Default | Notes |
|---|---|---|
| Host | 127.0.0.1 | |
| AGWPE Port | 8000 | |
| Auto-launch Soundmodem | Off | Starts the program at startup and on switching to Soundmodem mode |
| Exe Path | (empty) | Full path to the Soundmodem executable (no Browse button) |

**Local test (no radio)**

| Setting | Default | Notes |
|---|---|---|
| Cmd Port | 8500 | 1024 to 65535; must match the BBS instance |
| Data Port | 8501 | 1024 to 65535; must match the BBS instance |
| Connect as | (empty) | Empty: your own callsign |

The panel also repeats the BBS setup steps from [5.6](#56-local-test-no-radio).

**KISS TNC** (see [5.7](#57-kiss-tnc))

| Setting | Default | Notes |
|---|---|---|
| Connect via | Bluetooth or USB serial port (COM) | Or Bluetooth Low Energy (BLE), or TCP |
| Serial port | (none) | With **Refresh** |
| Baud rate | 9600 | 1200 to 115200. Not used over Bluetooth. |
| BLE device | (none) | With **Scan**, or type the address |
| BLE service | (empty) | Empty: the standard KISS-over-BLE service |
| TCP host / TCP port | 127.0.0.1 / 8001 | Direwolf's KISS port is 8001 |
| TNC port | 0 | 0 to 15 |
| Send TXDELAY, persistence and slot time to the TNC | On | Off keeps the radio's own settings |
| TXDELAY | 300 ms | |
| Persistence | 63 | 0 to 255 (63 = 25 %) |
| Slot time | 100 ms | |
| Init commands | (empty) | Text sent before KISS starts; `\r` separates commands |
| Packet length | 128 | 16 to 256 bytes |
| Window (MAXFRAME) | 4 | 1 to 7 |
| Retry time (FRACK) | 7 s | 1 to 30 s, longer through digipeaters |
| Retries | 10 | 1 to 30 |

### 8.3 Security

| Setting | Default | Notes |
|---|---|---|
| Auto-respond to HMAC challenges | On | Log in automatically with saved passwords |
| Show auth protocol messages in terminal (debug) | Off | Shows the raw `;AUTH` lines |

Passwords themselves are managed in **Settings → Security / Passwords...** (section 6.2).

### 8.4 Macros

Eight rows of **Label** and **Command**. Defaults are listed in [4.5](#45-macro-bar).

### 8.5 Settings without a field in the dialog

These live only in `settings.json`. Edit the file only while Aether Term is closed; it is
rewritten on exit.

| Key | Default | Meaning |
|---|---|---|
| `update_branch` | `main` | Branch a git install updates from |
| `skipped_update_version` | (none) | Set by **Skip This Version** |
| `tactical_callsign` | (none) | Tactical address sent after login when no profile sets one |
| `target_history`, `via_history`, `last_via1`, `last_via2` | | The dropdown histories |

---

## 9. Working with Aether BBS

### 9.1 Link type (;TRANSPORT)

Once the BBS has sent a line ending in CR LF (the Aether BBS does in its greeting), Aether Term
sends `;TRANSPORT?`. The Aether BBS answers with the link type it sees for your session, for
example `;TRANSPORT VARA_FM`. Aether Term hides that answer and shows it in the status bar as
`BBS link: VARA_FM`.

BBSes that end lines with a bare CR, such as BPQ nodes, are never sent `;TRANSPORT?`, because
they would take it as a bad command. Only the first `;TRANSPORT` line within 20 seconds of the
question is hidden; any other `;TRANSPORT` line is shown as normal text.

### 9.2 Tactical address

A tactical address lets you send and poll Winlink mail under an address such as `BRECKEN`. It
must already be set up on the BBS. Put it in a profile's **Tactical Address** field. Two seconds
after a successful automatic login, Aether Term sends `;TACTICAL <address>`. The BBS's answer is
shown as:

- `[TACTICAL] Address activated: <address>` (green)
- `[TACTICAL] Address cleared`
- `[TACTICAL] Rejected: <reason>` (yellow)

The address is sent only after `;AUTH OK`, so it needs a saved password. You can also use the
BBS's own `TACTICAL addr` command by typing it.

### 9.3 Chat rooms

When the BBS says you joined a room (a line with "Joined room *NAME*." and "Type /EXIT"), the
status bar shows `CHAT: NAME`. It disappears when the BBS says you left the room, when the chat
ends, or when the session ends.

### 9.4 Commands

**Help → BBS Commands Reference** lists the common Aether BBS commands: `L`, `R #`, `S call`,
`SW call`, `K #`, `N`, `LB`, `RB #`, `FL`, `FG`, `WL`, `WLREG`, `TACTICAL`, `H`, `I`, `MH`, `CH`,
`B` and more. The BBS's own `H` command is the authority for what it supports.

### 9.5 Session length

Aether Term has no idle timer of its own: it keeps a session open until you disconnect, the BBS
or the modem ends it, or the modem link is lost. When the BBS ends the session, you see
`*** DISCONNECTED ***`.

---

## 10. Troubleshooting

### 10.1 Messages and what to do

| Message | Meaning and fix |
|---|---|
| `[ERROR] Cannot connect to modem at <host>:<port> — ...` followed by "Tip: Aether Term is set to *&lt;mode&gt;*. Make sure the *&lt;mode&gt;* modem is running." | The modem program did not answer on its command port after **Max Retries** attempts. Start it, check the port, or switch to the right mode. In Aether HF mode the tip adds that Aether HF's host port is off by default (Setup step 5, "Host programs"). |
| `[ERROR] Cannot connect to Soundmodem at <host>:<port>` | Soundmodem or the TNC is not running, or its AGWPE port differs. |
| `[ERROR] Lost connection to modem` / `Lost connection to Soundmodem` | The modem program closed or crashed. The radio is unkeyed. |
| `[MODEM] Command rejected: WRONG (cmd: ...)` | The modem refused a command; the command is named. A rejected `CONNECT` ends the attempt. |
| `[MODEM] Connection attempt cancelled` | The modem gave up calling (`CANCELPENDING`). |
| `Remote station is busy` | The modem reports the channel or station busy. |
| `[MODEM] The modem's sound card would not open — it can neither hear nor transmit.` | `MISSING SOUNDCARD` from the modem. Check the audio device in the modem's setup. |
| `[MODEM] VARA reports this link as unregistered — VARA FM requires a VARA license to connect through digipeaters.` | `LINK UNREGISTERED` on a digipeated VARA FM call. |
| **PTT Unavailable** dialog / `Connect stopped: <method> PTT can't key the radio` | OmniRig, rigctld or FLrig could not be reached. Start it, or pick another method in **Settings → Modem Configuration → HF PTT Control**. See [5.3](#53-vara-fm-and-vara-hf). |
| `[PTT] <method> not connected` / `[PTT] <method> PTT command failed` | A keying command did not reach the radio during the session. |
| `[PTT] PTT watchdog: forced release after timeout` | The radio was keyed 90 s with no `PTT OFF`. Check the modem. |
| `OmniRig not running — start OmniRig for HF PTT control` (at startup) | OmniRig is the PTT method (the default) but is not running. Ignore it if you do not use VARA HF. |
| `pywin32 not installed — OmniRig PTT unavailable` (at startup) | Source install without pywin32: `pip install pywin32`. |
| `[AETHER] <problem>` then `Not connecting. Fix the above in Aether HF and try again.` | The Aether HF preflight found a problem. See [5.4](#54-aether-hf). |
| `[AETHER] Control API not reachable at http://...:8515 — connecting over the host port without status checks.` | Aether HF's control API did not answer. The call still goes out. |
| `[AETHER] The modem is busy (...)` | A session started from Aether HF's own panel is in progress. |
| `[AETHER] The modem on this port reports "...", not Aether HF.` | Another modem (often VARA HF) holds port 8300. Close it or change the port. |
| `[AETHER] No session with <target>. ...` | The call ended without a session. Check that the other station runs Aether HF on the same bandwidth; Aether HF's Log tab has the reason. |
| `Aether HF not found.` | Install Aether HF or set its path in **Settings → Modem Configuration**. |
| `<mode> modem not found.` / `<mode> executable not found: <path>` | Auto-launch is on but the program is not at the path. Set the path or turn auto-launch off. |
| `Digipeaters are supported with VARA FM, Soundmodem and a KISS TNC.` | Set Via 1 and Via 2 to None for this mode. |
| `'<call>' is not a valid digipeater callsign.` / `At most 2 digipeaters ...` | Fix the Via fields. |
| `No answer from <target> in 60 s — call cancelled` | Soundmodem call not answered. |
| `Local test: can't listen on 127.0.0.1 ports 8500/8501 (...)`, status bar `Local test: ports in use` | Another program uses those ports. Choose others in **Settings → Modem Configuration → Local test**, and change the BBS instance to match. |
| `Local test: no BBS has attached yet — start its local test instance first.` / `Local test: the BBS has not attached to ports ... yet.` | Start or restart the BBS instance (BBS Settings → Instances, or its dashboard). |
| `Local test: the BBS has not sent its callsign (MYCALL) yet.` | The BBS is still starting. Wait and press Connect again. |
| `TNC: cannot open COM<n>: ...` | The port is wrong or another program holds it. For a Bluetooth radio, check that it is paired, switched on and in range, and that you chose the outgoing COM port. |
| `TNC: cannot connect to the TNC at <host>:<port>` | Direwolf or the network TNC is not running, or its KISS port differs. |
| `TNC: no serial port chosen ...` / `TNC: no Bluetooth LE device chosen ...` | Pick the port or device in **Settings → Modem Configuration → KISS TNC**. |
| `TNC: pyserial is not installed` / `TNC: Bluetooth LE needs the bleak package ...` | Source install only: `pip install pyserial bleak`. |
| `TNC: cannot connect to <address> over Bluetooth LE: ...` / `... has no KISS TNC service ...` | The radio is off, out of range, connected to another device (a phone app), or its KISS TNC is not turned on. |
| `TNC: no answer from <target> after <n> tries` | The call was not answered. Check the frequency, the radio's TNC speed (1200 / 9600) and the target callsign. |
| `TNC: <target> is busy or refused the call` | The station answered with DM. |
| `TNC: link lost: no answer from <target> after <n> polls` | The other station stopped answering during the session. |
| `Lost the TNC (<link>): ...` | The COM port, Bluetooth link or TCP connection closed (radio switched off, out of range). |
| `[AUTH] No saved password — manual auth required` | See [6.3](#63-no-saved-password). |
| `[AUTH] Authentication FAILED ✗ — check saved password` | The saved password is wrong for this BBS, or a different entry was used (check the lookup order in [6.2](#62-saving-passwords)). |
| `[WLREG] No BBS password saved — cannot encrypt Winlink password` | Save the BBS password first. |
| `Not connected — command not sent.` | A macro was clicked with no session. |
| `Disconnect before switching to ...` | Mode changes are locked during a call. (In Settings the mode buttons are greyed out then.) |
| `Hamlib is set to its Dummy rig, which keys no radio. ...` | Choose your radio's model in **Settings → Modem Configuration → HF PTT Control → Rig Model**. |
| `[AUTH] Automatic login is off (Settings → Security) — manual auth required` | **Auto-respond to HMAC challenges** is off. Type the answer, or turn it back on. |
| `Settings could not be read (...); kept as settings.json.unreadable-<time>` | `settings.json` was damaged. Aether Term started from defaults and kept the old file next to it so you can recover it. |
| `Saved passwords could not be read (...); kept as passwords.enc.unreadable-<time>` | `passwords.enc` could not be decrypted (for example after copying it from another setup). It was kept aside; the password list starts empty. |
| **Aether Term — unexpected error** dialog | An internal error. The details are in the program log; Aether Term keeps running. Restart it if something does not work. |
| **Aether Term could not start** dialog | A startup failure. The details are in the program log. |

### 10.2 Common problems

**Connect does nothing useful in VARA HF mode, and the radio never transmits.** Check the PTT
method. With *None (VOX)* nothing is keyed by Aether Term. With *Hamlib*, check that the rig model
is your radio (Connect stops while it is *Hamlib Dummy*). With OmniRig, check that OmniRig shows the radio online.

**The BBS answers but my commands are garbled or ignored.** Aether Term answers in the BBS's own
line-end style once it has seen it. A BPQ node says nothing until spoken to, so your first line
goes out with a bare CR. If problems continue, the program log shows "BBS line ends: CR" or "CR
LF".

**Automatic login does not happen.** Check that **Auto-respond to HMAC challenges** is on, and that
the Password Manager has an entry whose Operator is the callsign in the window title (any SSID), or
is `(any)`.

**Local test: the BBS never attaches.** Start Aether Term in Local test mode before starting the
BBS instance, and check that the instance's ports match. (The BBS always reaches VARA on
`127.0.0.1`; its instance form has no Host field.)

### 10.3 Logs

- **Program log**: `%USERPROFILE%\Aether Term\logs\aether-term.log` (`~/Aether Term/logs/` on
  Linux). It records every modem command and event, PTT activity, AGWPE and AX.25 (KISS) frames,
  update checks and errors. Include it with a bug report.
- **Session logs**: in the same folder, one per session (see [7.4](#74-session-logs)).
- If `start_aether_term.bat` ends with an error, it prints the program log's path.

Report bugs on the [GitHub repository](https://github.com/KK4ODA/aether-term).

---

## 11. Keyboard and command line

| Key | Where | What it does |
|---|---|---|
| Enter | Command line | Sends the line to the BBS |
| Up / Down | Command line | Steps through the last 100 commands typed since Aether Term started (Down past the newest clears the line) |
| Ctrl+Shift+C | Anywhere | File → Connect |
| Ctrl+Q | Anywhere | Exit |
| Alt + underlined letter | Menu bar | Opens that menu (File, Settings, Aether HF, Help) |

Notes on the command line:

- It is enabled only while connected, and gets the focus when a session starts.
- Leading and trailing spaces are removed; an empty line is not sent.
- Lines go out with the BBS's own line end: CR LF to the Aether BBS, a bare CR to BPQ and most
  packet nodes.
- Text is sent as UTF-8.
