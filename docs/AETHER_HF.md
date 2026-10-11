# Aether HF integration

How Aether Term works with the [Aether HF](https://github.com/KK4ODA/aether-hf) modem. For setup
steps, see the [README](../README.md#using-aether-hf).

## Two interfaces

Aether Term uses two of Aether HF's interfaces:

| Interface | Address | Used for | Code |
|---|---|---|---|
| VARA-compatible host port | TCP `8300` (commands), `8301` (data) | The session: `MYCALL`, `BW…`, `CONNECT`, `DISCONNECT`, and the BBS traffic | `src/vara/modem.py` (shared with VARA FM/HF) |
| Control API | HTTP `POST http://127.0.0.1:8515/v1/<method>` | Read-only status: version, bandwidth, rung, host port on/off, rules, keying and sound card faults | `src/aether/control.py` |

The host port is the same one Winlink Express, Pat and VarAC use, as specified in Aether HF's
[`docs/spec/host-interfaces.md`](https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/host-interfaces.md).
The control API is specified in
[`docs/spec/control-api.md`](https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/control-api.md).
Aether Term calls only `status` and `capabilities` on it. It never changes the modem's
settings. A loopback connection needs no token.

## Command sequence

On **Connect** in Aether HF mode:

1. **Preflight** (control API `status`). The call is not sent when:
   - `host.enabled` is false: the host port is off (Aether HF Setup step 5)
   - `regulatory.policy` is `unset` or `broken`: Aether HF transmits nothing
   - `regulatory.indicator.verdict` is `blocked` at the current dial
   - `ptt_fault` or `audio_fault` is set

   If the control API cannot be reached (for example a remote modem with the API bound to
   loopback), Aether Term warns and continues over the host port alone.
2. **Host port**: `DISCONNECT` (Aether answers `OK` and ends only sessions this program
   started), `MYCALL <call>`, `COMPRESSION OFF`, `BW2300` or `BW500`, `VERSION`.
3. `VERSION` must answer `VERSION Aether HF <version>`. Any other answer means another modem
   (such as VARA HF) holds the port, and Aether Term warns before the call goes out.
4. `CONNECT <mycall> <target> [VIA …]`.

## Notifications handled

| Line from Aether HF | What Aether Term does |
|---|---|
| `BUFFER 0` (first line on attach), `IAMALIVE`, `ENCRYPTION DISABLED`, `LINK REGISTERED`, `REGISTERED`, `BUSY ON/OFF` | Ignored |
| `PENDING` | "Connection pending..." |
| `CONNECTED <caller> <called> <bandwidth>` | Session up. The remote is whichever callsign is not ours, and the bandwidth goes in the status bar |
| `BITRATE (<mode>) <bps> BPS` | Link speed in the status bar |
| `SN <dB>` | S/N label and graph |
| `PTT ON` / `PTT OFF` | Keys the radio only when *Aether HF keying is "host program"* is ticked |
| `MISSING SOUNDCARD` | Error in the terminal |
| `DISCONNECTED` with no session first | Asks the control API why, and explains |
| `WRONG` | Shown with the command that was rejected (for example a `BW500` refused mid-session) |

## Keying the radio

Aether HF normally keys the radio itself, and its regulatory check judges every transmission
at the dial before keying. In that setup Aether Term does **not** start OmniRig PTT.

If Aether HF's Setup step 2 is set to **host program**, tick *Aether HF keying is "host
program"* in Aether Term. Aether Term then keys the radio on `PTT ON` with the HF PTT method
(OmniRig), the same as for VARA HF. Aether HF's rules check is off in that mode, so the
operator checks every transmission.

## Auto-launch

With *Start Aether HF with Aether Term* ticked, Aether Term starts the desktop application
(`%LOCALAPPDATA%\Aether HF\aether-hf.exe` unless another path is set) and closes it on exit.
If the control API already answers, Aether HF is running and no second copy is started. A
headless `aetherd` gateway is not started by Aether Term; point **Host** at it instead.

## Status monitor

While Aether HF is the selected modem, `status` is polled every 2 seconds on a background
thread (`AetherMonitor`). `capabilities` is fetched again whenever the bandwidth changes, so
the rung index can be shown by name. The poll stops when another modem is selected.
