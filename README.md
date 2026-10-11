# VARA Term

VARA BBS Terminal Client with HMAC-SHA256 authentication, rig control, and macro support.

A PyQt6 desktop application for connecting to amateur radio BBS systems over VARA FM and VARA HF modems.

## Features

- Connect to VARA BBS stations over FM and HF
- Automatic HMAC-SHA256 authentication
- Encrypted Winlink registration (WLREG) for checking email via BBS
- OmniRig, FLrig, and Hamlib rig control / PTT support
- Automatic FM/HF mode switching with modem management
- OmniRig availability check at startup
- Connection profiles and target history
- Configurable macro buttons with BBS command reference
- Real-time S/N graph
- Session logging
- Dark theme terminal display
- Internet connectivity status from BBS

## Quick Start

1. Install dependencies: `pip install -r requirements.txt`
2. Run: `python src/main.py` (or double-click `start_vara_term.bat`)
3. Configure your callsign in Settings > Terminal Setup
4. Enter the target BBS callsign and click Connect

<!-- tota-support:start -->
## Support

VARA Term is free and stays free. It is written by KK4ODA, who also runs
[Tiles on the Air](https://tilesontheair.com), a free program for portable
operators, and both are kept going by the people who use them. If VARA Term is
useful to you, a contribution through the
[Tiles on the Air giving page](https://tilesontheair.com/Giving) helps keep this tool and Tiles
running. Nothing is ever locked behind it, and a bug report or an on-air
report helps just as much.
<!-- tota-support:end -->

## Contributors

- **KK4ODA** (Facundo) — Author
- **Claude** (Anthropic) — Co-developer
