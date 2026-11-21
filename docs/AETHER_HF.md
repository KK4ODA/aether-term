# Aether HF integration

How Aether Term works with the [Aether HF](https://github.com/KK4ODA/aether-hf) modem. For setup
steps, see the [README](../README.md#using-aether-hf).

Checked against Aether HF `0.2.0-beta.168` (link protocol 13), November 2026.

## Two interfaces

Aether Term uses two of Aether HF's interfaces:

| Interface | Address | Used for | Code |
|---|---|---|---|
| VARA-compatible host port | TCP `8300` (commands), `8301` (data) | The session: `MYCALL`, `BW…`, `CONNECT`, `DISCONNECT`, `ABORT`, and the BBS traffic | `src/vara/modem.py` (shared with VARA FM/HF) |
| Control API | HTTP `POST http://127.0.0.1:8515/v1/<method>` | Read-only: version, bandwidth, rung, host port and who holds it, rules, keying and sound card faults, why a call failed | `src/aether/control.py` |

The host port is the same one Winlink Express, Pat and VarAC use, as specified in Aether HF's
[`docs/spec/host-interfaces.md`](https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/host-interfaces.md).
The control API is specified in
[`docs/spec/control-api.md`](https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/control-api.md).
Aether Term calls only `status`, `capabilities` and `config.get` on it (the last only to read
`[ptt] kind`). It never changes the modem's settings. A loopback connection needs no token.

## Command sequence

On **Connect** in Aether HF mode:

1. **Preflight** (control API `status` and `config.get`). The call is not sent when:
   - `host.enabled` is false: the host port is off (Aether HF Setup step 5)
   - `host.command_address` names another port than Aether Term's Command Port (checked when
     Host is this computer). Aether HF's Winlink-program finder sets the host port to the one a
     program already used, so it is not always 8300.
   - `regulatory.policy` is `unset` or `broken`: Aether HF transmits nothing
   - `regulatory.indicator.verdict` is `blocked` at the current dial
   - `ptt_fault` or `audio_fault` is set
   - `config.ptt.kind` is `host` (Aether HF Setup step 2: *host program*) and *Aether HF keying
     is "host program"* is not ticked: nothing would key the radio. Without `config.get` (a
     daemon run with no configuration file), `status.ptt` reading "the host program …" says the
     same.
   - `status.air` is present and not `hf` (Aether FM, when it comes)

   Then:
   - If *Aether HF keying is "host program"* is ticked but Aether HF keys the radio itself
     (`cat`, `serial`, `rigctld`, `flrig`, `cm108`), a warning says only one program should key
     it. The call still goes out.
   - If `host.connected` is true, another program holds the host port. Aether HF serves one host
     at a time and the newest connection replaces the old one, so Aether Term asks before taking
     it (default *No*). `status.claims` entries of kind `host` give the callsigns that program
     holds.

   If the control API cannot be reached (for example a remote modem with the API bound to
   loopback), Aether Term warns and continues over the host port alone.
2. **Host port**: `DISCONNECT` (Aether answers `OK` and ends only sessions this program
   started), `MYCALL <call>`, `COMPRESSION OFF`, `BW2300` or `BW500`, `VERSION`.
   Aether HF answers every command, in order, so Aether Term waits for the `OK`/`WRONG` of
   `MYCALL` and `BW` (5 s at most) instead of fixed pauses:
   - `MYCALL` is `WRONG` for a callsign the link layer cannot carry (A–Z, 0–9, `-`, `/`, at most
     nine characters).
   - `BW<n>` is `WRONG` while a session, call, probe or transmission is under way: the station
     moves only between sessions. The adapter still marks the bandwidth as asked for, so a
     `CONNECT` after a refused `BW` would go out in the bandwidth the station runs.

   Either `WRONG` stops the setup: no `CONNECT` is sent.
3. `VERSION` must answer `VERSION Aether HF <version>`. Any other answer means another modem
   (such as VARA HF) holds the port, and Aether Term warns before the call goes out.
4. `CONNECT <mycall> <target>`. Digipeaters are refused in Aether HF mode before anything is
   sent: since 2026-11-19 Aether HF answers `CONNECT … VIA …` with `WRONG` (it relays nothing).

## Notifications handled

| Line from Aether HF | What Aether Term does |
|---|---|
| `BUFFER <n>` (`BUFFER 0` is the first line on attach), `IAMALIVE` (every 10 s), `ENCRYPTION DISABLED`, `LINK REGISTERED`, `REGISTERED <call>`, `BUSY ON/OFF`, `CQFRAME <call> <bw>` (a beacon heard) | Ignored |
| `PENDING`, `CANCELPENDING` | Called-side lines. Aether Term never says `LISTEN ON`, so Aether HF does not answer calls to its callsign while it is attached and these do not come |
| `CONNECTED <caller> <called> <bandwidth>` | Session up. The remote is whichever callsign is not ours, and the bandwidth goes in the status bar |
| `BITRATE (<mode>) <bps> BPS` | Link speed in the status bar |
| `SN <dB>` | S/N label and graph |
| `PTT ON` / `PTT OFF` | Keys the radio only when *Aether HF keying is "host program"* is ticked. Never swallowed, not even during the opening `DISCONNECT` |
| `MISSING SOUNDCARD` | Error in the terminal |
| `DISCONNECTED` with no session first | Asks the control API why, and explains (below) |
| `WRONG` | Shown with the command that was rejected |

## Why a call failed

After a `DISCONNECTED` with no session, Aether Term reads `status` again:

- Any preflight problem is printed.
- `bandwidth.mismatch` with `what` = `version` (the called station answered in another link
  protocol: one of the two needs to update) or `suggest` (no answer, but the same operator was
  heard within 30 minutes under another SSID) is printed in Aether HF's own words, when its
  `callsign` has the target's base callsign and its `at_ms` is no older than a minute before the
  call. Aether HF repeats a station's mismatch only once a minute, so a second try within the
  minute still shows it.
- Otherwise the terminal says that Aether HF talks only to Aether HF stations on the same
  bandwidth and link protocol, and that its Log tab has the reason.

## Disconnecting

`DISCONNECT` closes in order: the caller sends what is queued for up to 60 s (ADR-0072), then
the closing Morse identifier (always for a US callsign, ADR-0075), and `DISCONNECTED` comes only
after it. Aether Term says so. A second Disconnect sends `ABORT` (the session ends now) and stays
attached for the `DISCONNECTED`; a third closes the modem link.

Closing the link mid-session does not hurry Aether HF: a host program that leaves has its session
closed as `DISCONNECT` does. With *host program* keying it also leaves nobody to key the radio for
the last frames and the identifier, which is why the second press aborts instead.

## Keying the radio

Aether HF normally keys the radio itself, and its regulatory check judges every transmission
at the dial before keying. In that setup Aether Term does **not** start its own PTT.

If Aether HF's Setup step 2 is set to **host program**, tick *Aether HF keying is "host
program"* in Aether Term. Aether Term then keys the radio on `PTT ON` with the HF PTT method
(OmniRig, Hamlib rigctld or FLrig), the same as for VARA HF. Aether HF's rules check is off in
that mode, so the operator checks every transmission. Aether HF's first audio follows `PTT ON`
by its `lead_ms` (150 ms unless set). The preflight checks that the two settings agree.

## Auto-launch

With *Start Aether HF with Aether Term* ticked, Aether Term starts the desktop application
(`%LOCALAPPDATA%\Aether HF\aether-hf.exe` unless another path is set) with no arguments. If the
control API already answers, Aether HF is running and no second copy is started. A headless
`aetherd` gateway is not started by Aether Term; point **Host** at it instead.

On exit or a mode switch, Aether Term asks Aether HF's window to close (`taskkill /PID` without
`/F` on Windows, which posts `WM_CLOSE`; `SIGTERM` elsewhere), the same as its close button.
The window then stops its modem in order: a session's DISC and closing identifier, then the
transmitter released (control API `shutdown` semantics). It may ask the operator first when a
session is under way. Aether Term waits 5 s and then leaves it to finish. It never force-kills
the process tree: that killed the `aetherd` sidecar mid-transmission, and with CAT keying
(`TX1;`) the radio could stay keyed.

## Status monitor

While Aether HF is the selected modem, `status` is polled every 2 seconds on a background
thread (`AetherMonitor`). `capabilities` is fetched again whenever the bandwidth changes, so
the rung index can be shown by name. The poll stops when another modem is selected. One-shot
checks (preflight, the status dialog, the Settings Test button) also read `config.get`.

## Aether HF's KISS port

Aether HF has a KISS port (TCP 8100, off by default) for APRS programs and VarAC's broadcasts.
It carries each frame as an Aether datagram at rung 1 (tone-36, 54 bit/s) to other Aether
stations, and drops frames from KISS programs while a host program holds the command port
without `CHAT ON` (VARA's "Winlink priority"). Aether Term's KISS TNC mode can reach it over TCP,
but connected AX.25 that way is very slow; use the Aether HF mode.

## Aether FM (later)

Aether FM will be the same daemon with another air (Aether HF ADR-0112, ADR-0124, proposed). What
is known now, and how Aether Term stands:

- The host port speaks VARA FM's published commands, `VERSION` answers with Aether's own name,
  `BW` has no FM meaning, and `CONNECT … VIA …` is refused (no relaying in the first release).
  `VARAModem` already handles VARA FM's lines; the `VERSION` check accepts any Aether name.
- `status` and `capabilities` will carry `air: "fm"`. `AetherStatus.air` reads it, and the Aether
  HF mode refuses to call through a modem whose air is not HF.
- With legacy packet on, the KISS port becomes a real AX.25 TNC (1200/9600 baud) and an AGWPE
  port serves connected-mode packet programs: Aether Term's KISS TNC and Soundmodem (AGWPE)
  modes are the ones for that.

An Aether FM mode in Aether Term would be the Aether HF mode without `BW`, with the air checked
as `fm`.
