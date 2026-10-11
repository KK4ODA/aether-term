# Aether Term

BBS terminal client for amateur radio, with HMAC-SHA256 authentication, rig control, macros and
built-in support for the open-source [Aether HF](https://github.com/KK4ODA/aether-hf) modem.

Aether Term is a PyQt6 desktop application for connecting to amateur radio BBS systems over
**Aether HF**, **VARA HF**, **VARA FM**, and AGWPE packet TNCs (Soundmodem, Direwolf).

> **Formerly VARA Term.** The application was renamed when Aether HF support was added. Your
> settings, saved station passwords and Hamlib download are carried over automatically the
> first time Aether Term starts (see [Upgrading from VARA Term](#upgrading-from-vara-term)).

## Features

- Connect to BBS stations over Aether HF, VARA HF, VARA FM, or AGWPE packet
- **Aether HF integration**: live modem status in the status bar, a pre-connect check that
  explains in plain words why the modem would refuse a call (host port off, no rules chosen,
  keying or sound card fault), modem identity check, link speed and session bandwidth
- Automatic HMAC-SHA256 authentication — passwords never go over RF
- Encrypted Winlink registration (WLREG) for checking email via BBS
- OmniRig, FLrig and Hamlib rig control / PTT support
- Mode switching with modem auto-launch (VARA FM, VARA HF, Aether HF, Soundmodem)
- Connection profiles (per-profile operator, tactical address, mode and bandwidth) and
  target history
- Configurable macro buttons with BBS command reference
- Real-time S/N graph, session logging, dark theme terminal
- Internet connectivity status from the BBS

## Quick Start

1. Install dependencies: `pip install -r requirements.txt`
2. Run: `python src/main.py` (or double-click `start_aether_term.bat`)
3. Configure your callsign in **Settings → Terminal Setup**
4. Pick the modem in the toolbar (Aether HF, VARA HF, VARA FM or Soundmodem)
5. Enter the target BBS callsign and click **Connect**

A one-line installer for Windows (clones the repository, installs dependencies, creates a
desktop shortcut) is on the [project page](https://kk4oda.github.io/aether-term/).

## Using Aether HF

[Aether HF](https://github.com/KK4ODA/aether-hf) is an open-source HF data modem with a publicly
documented air interface. It speaks VARA HF's published TCP host interface, so Aether Term drives
it through the same command and data ports it uses for VARA, and additionally reads Aether HF's
own control API for status.

**On the air, Aether HF talks only to other Aether HF stations** — the compatibility is in the
software, not the signal. The BBS you call must be running Aether HF too, on the same bandwidth
(2300 Hz or 500 Hz) and the same link-protocol version.

### Setting it up

1. Install Aether HF from its [Releases](https://github.com/KK4ODA/aether-hf/releases) page
   (Windows installs per-user to `%LOCALAPPDATA%\Aether HF\`).
2. In **Aether HF**:
   - Setup step 1: choose the rules your station runs under (nothing is transmitted until you do).
   - Setup step 2: how the radio is keyed. The usual choice is to let **Aether HF own the radio**
     (CAT, serial, CM108 or `rigctld`), which keeps its regulatory check on every transmission.
   - Setup step 5: turn on **Host programs** (port 8300). It is off by default.
3. In **Aether Term**, select **Aether HF** in the toolbar, or in
   **Settings → Terminal Setup → Modem**. Under **Settings → Modem Configuration → Aether HF Modem**:

   | Setting | Default | Notes |
   |---|---|---|
   | Host | `127.0.0.1` | Where Aether HF runs |
   | Command Port | `8300` | Data port is always command + 1 |
   | Control API Port | `8515` | Read-only status; no token needed on loopback |
   | Bandwidth | `2300` | `BW2300` / `BW500` — both stations must match |
   | Keying is "host program" | off | Turn on only if Aether HF Setup step 2 is *host program*; Aether Term then keys the radio with the PTT method below (OmniRig) |
   | Start Aether HF with Aether Term | off | Launches `aether-hf.exe`, unless Aether HF is already running |

   **Test Aether HF** in that panel asks the modem for its status and lists anything that needs
   attention.

### What you see

- **Status bar** — `Aether <version> · <bandwidth> · <state> · <rung>`, green when ready, red when
  something blocks transmitting. Click it for the full status.
- **On Connect** — the modem's status is checked first. If the host port is off, no rules are
  chosen, or the modem cannot key the radio, Aether Term says so and does not send the call.
- **After connecting** — the modem's `VERSION` is checked (a VARA modem left on port 8300 is
  caught), and `CONNECTED`/`BITRATE` fill in the session bandwidth and link speed.
- **A call that ends with no session** — Aether Term asks the modem why and explains it.
- **Aether HF menu** — modem status, open the station panel in a browser, the host-program
  setup guide, and the download page.

Details of the protocol mapping are in [`docs/AETHER_HF.md`](docs/AETHER_HF.md).

## Upgrading from VARA Term

- **Settings and passwords**: on first start, `%APPDATA%\VARA Term\` is copied to
  `%APPDATA%\Aether Term\` (settings, encrypted station passwords, downloaded Hamlib). The old
  folder is left untouched, so going back to VARA Term still works.
- **Logs** are now written to `%USERPROFILE%\Aether Term\logs\aether-term.log`.
- **Installer**: the Aether Term installer upgrades an existing VARA Term installation in place.
- **Git installs**: GitHub redirects the old repository URL, so auto-update keeps working. To
  point an existing clone at the new name:
  `git remote set-url origin https://github.com/KK4ODA/aether-term.git`

## Building

See [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) for the Windows installer and portable build.

<!-- tota-support:start -->
## Support

Aether Term is free and stays free. It is written by KK4ODA, who also runs
[Tiles on the Air](https://tilesontheair.com), a free program for portable
operators, and both are kept going by the people who use them. If Aether Term is
useful to you, a contribution through the
[Tiles on the Air giving page](https://tilesontheair.com/Giving) helps keep this tool and Tiles
running. Nothing is ever locked behind it, and a bug report or an on-air
report helps just as much.
<!-- tota-support:end -->

## License

Copyright (C) 2026 KK4ODA. Released under the GNU General Public License v3.0, see [LICENSE](LICENSE). The GPL is required because Aether Term is built on PyQt6, which is licensed under GPL v3.

Aether HF is a separate program (MIT OR Apache-2.0). Aether Term talks to it only over its
documented TCP interfaces and does not include any of its code. VARA is a product of EA5HVK;
Aether Term is not affiliated with it.

## Contributors

- **KK4ODA** (Facundo) — Author
- **Claude** (Anthropic) — Co-developer
