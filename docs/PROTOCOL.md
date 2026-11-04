# Protocol (uart-gateway)

> **Authoritative contract:** the full interface specification is frozen in
> [`INTERFACE.md`](./INTERFACE.md). This file is the wire-protocol deep-dive.
> Flash / yield mode and deliberate modem-write commands are **out of scope**
> (removed 2026-11-04 — they were never requested).

Line-based, UTF-8 text protocol over a **Unix domain socket** (default
`/tmp/uart-gateway.sock`). **Exactly one client is the *controller*** (may `SEND`);
others may subscribe as *monitors* (RX broadcast only). A second client that
issues `SEND` while a controller exists receives `BUSY`. **Occupy = connect,
release = disconnect** — neither touches the serial port, so neither affects
DTR/RTS.

All frames `\n`-terminated. The binary framing rules (`DATA <len>` block vs
`DATAHEX` single line) are in `INTERFACE.md` §1.3.

## Client → Gateway commands

| Command | Args | Meaning |
|---------|------|---------|
| `SEND <text>` | text (no embedded LF) | Transmit text (trailing `\r\n` per config) |
| `SENDHEX <hex>` | even-length hex | Transmit raw bytes |
| `RECV <timeout_ms>` | ms | Return received bytes up to timeout → `DATA` |
| `RECV_HEX <timeout_ms>` | ms | Return `DATAHEX <hex>` |
| `RECV_UNTIL <pat> <ms>` | pattern, ms | Block until pattern or timeout |
| `GET_MODEM` | — | Reply `MODEM DTR=x RTS=x CTS=x DSR=x` (read-only) |
| `STATUS` | — | Report state |
| `SUBSCRIBE` / `UNSUBSCRIBE` | — | RX broadcast on/off |
| `PING` | — | → `PONG` |
| `QUIT` | — | Close this connection (release entry point) |

## Gateway → Client replies

- `OK` — command accepted.
- `DATA <len>` then `<len>` bytes — received data (framed; see INTERFACE.md §1.3).
- `DATAHEX <hex>` — single-line hex-encoded received bytes.
- `MODEM DTR=x RTS=x CTS=x DSR=x` — read-only modem states.
- `STATUS <key=value ...>` — status snapshot.
- `PONG` — reply to `PING`.
- `RX <len>` then `<len>` bytes — broadcast to subscribers: a received chunk,
  binary-safe (mirrors `DATA`). Client renders as text/hex.
- `RXHEX <hex>` — single-line hex variant of the broadcast (AI-friendly).
- `BUSY` — request rejected: another client holds the controller role (or a
  transient condition blocks the action).
- `EVENT <type>` — async event. Types include `DISCONNECT`, `RECONNECT`,
  `PORT_LOST` (serial device disappeared, e.g. USB unplug), `PORT_RESTORED`
  (device reappeared, gateway re-opened and re-asserted safe state).
- `ERR <reason>` — command failed.

## Behaviour guarantees (the reason this project exists)

- Port `open()`ed **exactly once** at gateway start, held with `TIOCEXCL` +
  `flock(LOCK_EX)` → nothing else can open it → **no open-time reset during
  operation**.
- `HUPCL=0` → gateway release/exit does not drop DTR → **no reset on release**.
- DTR/RTS default to the safe run state; client connect/disconnect never moves
  them. (Only an explicit, user-initiated modem command would move them — out of
  current scope.)
- The single `open()` at launch still produces one pulse (kernel asserts DTR/RTS
  on open — see picocom `lowerrts.md`); it is a one-time, user-controlled event
  (start the gateway when ready to attach). The guarantee is therefore **"no
  reset on connect/disconnect"**, not "zero resets under all circumstances".
- On `PORT_LOST` the gateway holds the safe state and rejects client I/O until
  `PORT_RESTORED`; recovery stays exclusive.
