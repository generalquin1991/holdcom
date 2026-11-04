# Protocol (uart-gateway)

Line-based, UTF-8 text protocol over a **Unix domain socket** (default
`/tmp/uart-gateway.sock`) and/or an optional **TCP** listener bound to
`127.0.0.1` only. One client is the *controller* (may send); others may
subscribe as *monitors* (RX broadcast only). AI tools use the Python
client (`client/uart_client.py`) — they never touch the serial port.

All frames are `\n`-terminated. Requests from client → gateway; replies
gateway → client.

## Client → Gateway commands

| Command                  | Args                | Meaning |
|--------------------------|---------------------|---------|
| `SEND`                   | `<text>` or `HEX <hex>` | Transmit bytes to serial port |
| `RECV`                   | `<timeout_ms>`      | Return next received line(s) up to timeout |
| `RECV_UNTIL`             | `<pattern> <timeout_ms>` | Block until `<pattern>` seen or timeout |
| `SET_DTR`                | `0|1`               | Assert/clear DTR modem line |
| `SET_RTS`                | `0|1`               | Assert/clear RTS modem line |
| `RESET`                  | —                   | Toggle EN (one low pulse) → device reset |
| `BOOT`                   | —                   | esptool DTR/RTS dance → download mode |
| `STATUS`                 | —                   | Report port/baud/DTR/RTS/open state |
| `QUIT`                   | —                   | Close this client connection |

## Gateway → Client replies

- `OK` — command accepted.
- `DATA <len>` then `<len>` bytes — received serial data (framed).
- `ERR <reason>` — command failed.
- `EVENT <type>` — async event (e.g. `DISCONNECT`, `RECONNECT`).

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
