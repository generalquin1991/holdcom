# Protocol (uart-gateway)

> **Authoritative contract:** the full interface specification (wire protocol +
> C API + Python API + CLI + startup config) is frozen in
> [`INTERFACE.md`](./INTERFACE.md). This file is the wire-protocol deep-dive.
> If they disagree, `INTERFACE.md` wins.

Line-based, UTF-8 text protocol over a **Unix domain socket** (default
`/tmp/uart-gateway.sock`). One client is the *controller* (may send); others may
subscribe as *monitors* (RX broadcast only). AI tools use the Python
client (`client/uart_client.py`) — they never touch the serial port.

All frames are `\n`-terminated. Requests from client → gateway; replies
gateway → client. The binary framing rules (`DATA <len>` block vs `DATAHEX`
single line) are specified in `INTERFACE.md` §1.3.

## Client → Gateway commands

| Command                  | Args                | Meaning |
|--------------------------|---------------------|---------|
| `SEND <text>`            | text (no embedded LF) | Transmit text (trailing `\r\n` per `send-crlf` config) |
| `SENDHEX <hex>`          | even-length hex     | Transmit raw bytes (AI-safe) |
| `RECV <timeout_ms>`      | ms                  | Return received bytes up to timeout → `DATA` frame |
| `RECV_HEX <timeout_ms>`  | ms                  | Like `RECV`, reply `DATAHEX <hex>` (single line) |
| `RECV_UNTIL <pat> <ms>`  | pattern, ms         | Block until `<pattern>` seen or timeout |
| `SET_DTR <0\|1>`         | 0/1                 | Assert/clear DTR (post-polarity) |
| `SET_RTS <0\|1>`         | 0/1                 | Assert/clear RTS (post-polarity) |
| `GET_MODEM`              | —                   | Reply `MODEM DTR=x RTS=x CTS=x DSR=x` |
| `RESET`                  | —                   | Reset pulse sequence (config polarity/timing) |
| `BOOT`                   | —                   | Bootloader-entry DTR/RTS dance |
| `STATUS`                 | —                   | Report port/baud/DTR/RTS/open state |
| `SUBSCRIBE`              | —                   | Register as RX broadcast subscriber |
| `UNSUBSCRIBE`            | —                   | Cancel RX subscription |
| `FLASH_BEGIN`            | —                   | Enter flash mode → `FLASH_READY <slave_path>` |
| `FLASH_END`              | —                   | Exit flash mode |
| `PING`                   | —                   | Health check → `PONG` |
| `QUIT`                   | —                   | Close this client connection |
| `SHUTDOWN`               | —                   | Stop the gateway (admin) |

## Gateway → Client replies

- `OK` — command accepted.
- `DATA <len>` then `<len>` bytes — received serial data (framed; see §1.3).
- `DATAHEX <hex>` — single-line hex-encoded received bytes.
- `MODEM DTR=x RTS=x CTS=x DSR=x` — modem line states (post-polarity).
- `STATUS <key=value ...>` — status snapshot.
- `FLASH_READY <slave_path>` — pty slave path for the flashing tool.
- `BUSY` — request cannot be served now (flash mode active, etc.).
- `ERR <reason>` — command failed.
- `PONG` — reply to `PING`.
- `RX <line>` — broadcast to subscribers: a received line.
- `EVENT <type>` — async event (e.g. `DISCONNECT`, `RECONNECT`).

## Flash / yield mode (pty proxy)

`FLASH_BEGIN` makes the gateway create a pty pair and start a transparent
bridge (**before** replying), then reply `FLASH_READY <slave_path>`. The client
launches the flashing tool with `--port <slave_path>`; the tool `open()`s the
**pty**, not the real device, so there is no open-time pulse on hardware. The
bridge forwards bytes both ways and mirrors modem-control ioctls, so the tool's
reset sequence reaches the device faithfully. `FLASH_END` (or pty EOF) stops the
bridge and re-asserts the safe state. During flash mode the text protocol is
**suspended**; other clients get `BUSY`.

## Behaviour guarantees (the reason this project exists)

- The serial port is `open()`ed **exactly once** at gateway start and held
  with `TIOCEXCL` + `flock(LOCK_EX)` → nothing else (incl. pyserial) can
  open it → **no open-time reset during AI operation**.
- `HUPCL=0` → gateway exit does not drop DTR → no reset on shutdown.
- DTR/RTS default to the **safe run state** (ESP32: DTR=1, RTS=1 → EN high,
  IO0 high). `RESET`/`BOOT` toggle lines only on explicit request.

> Note: the single open at gateway startup still produces one pulse (kernel
> driver asserts DTR/RTS on open — see picocom `lowerrts.md`). This is a
> one-time, user-controlled event (start the gateway when ready to attach).
