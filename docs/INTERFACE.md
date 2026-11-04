# Interface Contract (frozen — minimal scope)

> **Scope note (2026-11-04):** Flash / yield (pty proxy) mode and all deliberate
> modem-write commands (`SET_DTR`, `SET_RTS`, `RESET`, `BOOT`) were added without
> being requested and have been **removed**. This contract now covers **only what
> was asked**: a reliable entry point for AI and the user to take over a USB
> serial port, where **occupy (connect)** and **release (disconnect)** never
> touch DTR/RTS and therefore never reset the target MCU **on connect/disconnect**.
> The gateway's own one-time launch `open()` produces the only unavoidable modem
> pulse (see §1, §6). Deliberate modem actions may be added later **only after
> explicit confirmation**.

This is a **generic** serial-takeover tool. No specific target hardware,
project, or personal context is assumed.

---

## 1. Wire protocol (client ↔ gateway)

Transport: **local Unix domain socket** only (default `/tmp/uart-gateway.sock`).
Framing: every request/reply is `\n`-terminated (LF). Binary is carried either
as a length-framed block or as hex on a single line (see `DATA` / `DATAHEX`).

**Occupy = the client connects to the socket. Release = the client disconnects.**
Neither action opens/closes the serial port (the gateway owns it), so neither
affects DTR/RTS. This is the core guarantee.

> **Scope of the guarantee (important).** The guarantee covers **client
> occupy/release only**. The gateway itself performs exactly one `open()` at
> launch; that single open makes the kernel driver assert DTR/RTS once. This
> launch-time pulse is unavoidable (driver behaviour, see `DESIGN.md` §1) and is
> a one-time, operator-initiated event — not something that recurs on connect/
> disconnect. We do **not** claim "zero resets under all circumstances"; we claim
> "repeated connect/disconnect never resets the target."

Exactly one client is the **controller** (may `SEND`); others may **subscribe**
as **monitors** (RX broadcast only). A second client that issues `SEND` while a
controller exists receives `BUSY`; the gateway enforces a single sender.

### 1.1 Client → Gateway commands

| Command | Args | Purpose |
|---------|------|---------|
| `SEND <text>` | text (no embedded LF) | Transmit text; trailing `\r\n` per `send-crlf` config. |
| `SENDHEX <hex>` | even-length hex | Transmit raw bytes (AI-safe). |
| `RECV <timeout_ms>` | ms | Return buffered received bytes up to timeout → `DATA` frame. |
| `RECV_HEX <timeout_ms>` | ms | Like `RECV`, reply `DATAHEX <hex>` (single line). |
| `RECV_UNTIL <pattern> <timeout_ms>` | pattern, ms | Block until `<pattern>` seen in the buffer or timeout. |
| `GET_MODEM` | — | Reply `MODEM DTR=x RTS=x CTS=x DSR=x` (read-only). |
| `STATUS` | — | Report state (keys in §5). |
| `SUBSCRIBE` | — | Register as RX broadcast subscriber (forward-only). |
| `UNSUBSCRIBE` | — | Cancel RX subscription. |
| `PING` | — | Health check → `PONG`. |
| `QUIT` | — | Close this client connection (= release entry point). |

### 1.2 Gateway → Client replies

| Reply | Meaning |
|-------|---------|
| `OK` | Command accepted. |
| `ERR <reason>` | Command failed. |
| `DATA <len>` | Header; then `<len>` raw bytes + trailing LF. |
| `DATAHEX <hex>` | Single-line hex-encoded received bytes. |
| `MODEM DTR=x RTS=x CTS=x DSR=x` | Read-only modem states (x∈{0,1}). |
| `STATUS <key=value ...>` | Status snapshot (keys in §5). |
| `PONG` | Reply to `PING`. |
| `RX <len>` | Broadcast to subscribers: `<len>` raw received bytes + trailing LF (binary-safe, mirrors `DATA`). Client renders as text/hex. |
| `RXHEX <hex>` | Single-line hex variant of the broadcast (AI-friendly). |
| `BUSY` | Request rejected: another client holds the controller role (or a transient condition blocks the action). |
| `EVENT <type>` | Async event. Types: `DISCONNECT`, `RECONNECT`, `PORT_LOST`, `PORT_RESTORED`, `OVERFLOW` (RX ring dropped oldest). |

### 1.3 Data framing rules

- `DATA <len>\n<bytes>\n`: `<len>` decimal byte count; reader consumes exactly
  `<len>` bytes after the header, then the terminating LF.
- `DATAHEX <hex>\n`: whole received buffer as hex on one line (AI-friendly).
- Broadcast frames use the same `<len>`/hex encoding so binary (no LF, embedded
  control chars) is carried losslessly.

### 1.4 RX buffering & delivery model

The gateway maintains a **ring buffer** of all received serial bytes (default
64 KiB). This resolves the send-then-receive race:

- `RECV` / `RECV_HEX` / `RECV_UNTIL` **drain from the ring buffer**, so a client
  that issues `SEND` and only later calls `RECV` still retrieves the response.
- `SUBSCRIBE` is **forward-only**: a subscriber receives bytes received *after*
  subscription, not the buffered history.
- On ring overflow the oldest bytes are dropped and `EVENT OVERFLOW` is emitted.

### 1.5 Controller role & state

- A single **controller slot** exists. It is granted to the first client that
  issues `SEND` while the slot is free.
- The slot is released when that client disconnects or sends `QUIT`.
- A `SEND` from any other client while the slot is held is rejected with `BUSY`.
- Monitors (subscribers) can never `SEND`.

---

## 2. C API (`gateway/serial.h`, `gateway/server.h`)

### 2.1 `serial.h`

```c
typedef struct serial serial_t;

typedef struct {
    int baud;          /* e.g. 115200 */
    int dtr_active;    /* 1 = high-active, 0 = low-active (default) — sets safe state */
    int rts_active;    /* 1 = high-active, 0 = low-active (default) */
} serial_cfg_t;

/* Open exactly once: O_RDWR|O_NOCTTY|O_NONBLOCK, TIOCEXCL, flock(LOCK_EX),
   cfmakeraw, set speed, CLOCAL, clear HUPCL, then assert SAFE DTR/RTS. */
serial_t *serial_open(const char *port, const serial_cfg_t *cfg);

/* Read-only modem lines (post-polarity). Any pointer may be NULL. */
int serial_get_modem(serial_t *s, int *dtr, int *rts, int *cts, int *dsr);

/* Raw byte I/O. read() honours timeout_ms (0 = poll, -1 = block). */
ssize_t serial_write(serial_t *s, const void *buf, size_t n);
ssize_t serial_read(serial_t *s, void *buf, size_t n, int timeout_ms);

/* Restore safe state, clear TIOCEXCL, close fd. HUPCL=0 ⇒ no DTR drop on
   release (this is what prevents a reset when the gateway lets go). */
int serial_close(serial_t *s);
```

### 2.2 `server.h`

```c
typedef struct {
    serial_t   *ser;
    const char *sock_path;   /* Unix socket path; created chmod 0600 */
} server_cfg_t;

/* Blocking: owns the poll() loop over [serial fd, listen fd, client fds],
   dispatches the wire protocol, broadcasts RX. Client connect/disconnect never
   touches the serial port's modem lines. Enforces a single controller
   (§1.5) and handles hotplug (PORT_LOST / PORT_RESTORED). */
int server_run(const server_cfg_t *cfg);
```

---

## 3. Python client API (`client/uart_client.py`)

```python
class UartGateway:
    def __init__(self, sock_path="/tmp/uart-gateway.sock"): ...
    def connect(self) -> None: ...        # occupy entry point
    def send(self, text, newline=True) -> None: ...
    def send_hex(self, hexstr) -> None: ...
    def recv(self, timeout_ms=1000) -> bytes: ...
    def recv_until(self, pattern, timeout_ms=5000) -> bytes: ...
    def recv_hex(self, timeout_ms=1000) -> str: ...
    def get_modem(self) -> dict: ...       # {"dtr":..,"rts":..,"cts":..,"dsr":..}
    def status(self) -> dict: ...
    def subscribe(self): ...               # context manager yielding RX iterator
    def close(self) -> None: ...           # release entry point
```

`connect()` / `close()` are the occupy/release actions. They never affect
DTR/RTS on the device.

---

## 4. CLI surface (`client/cli.py`)

```
uart-cli send "AT\r\n"
uart-cli recv -t 1000
uart-cli recv-until "OK" -t 5000
uart-cli status
uart-cli attach            # interactive console (see below)
```

### 4.1 Interactive console (`attach`)

The human-facing use of the same entry point. **No new gateway command is
required** — `attach` is pure client-side wiring of already-frozen primitives:

- On start: send `SUBSCRIBE` so the gateway broadcasts every received chunk as a
  binary-safe `RX <len>` frame; render each to the terminal in real time (text
  where printable, escaped otherwise).
- Put the **local** terminal into raw/cbreak mode (no OS line editing, no
  cooked echo) so each keystroke is forwarded immediately.
- Each keystroke (or keystroke group) is sent via `SEND` (printable text) or
  `SENDHEX` (control bytes such as `0x03` / Ctrl-C). **Ctrl-C is forwarded to the
  device, not used to kill the client.** The client only intercepts the escape
  key.
- An escape key (default `Ctrl-]`) detaches: send `UNSUBSCRIBE` then `QUIT`.
- Because occupy/release are just socket connect/disconnect, opening or leaving
  the console never resets the target — exactly the guarantee this tool exists
  for.

This is the non-resetting replacement for `screen` / `minicom` / `pyserial`'s
interactive use.

---

## 5. Gateway startup / configuration interface

```
uart-gateway -p <port> -b <baud> -s <sock_path>
             [-P <dtr_polarity>] [-R <rts_polarity>]
             [--send-crlf] [--daemon] [-l <logfile|stderr>]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `-p` | required | Serial device path. On macOS use a `/dev/cu.*` callout device (not `/dev/tty.*`). May be absent at start (gateway waits for hotplug). |
| `-b` | `115200` | Baud rate. |
| `-s` | `/tmp/uart-gateway.sock` | Unix socket path. `chmod 0600`. On start, if it exists the gateway probes it; if a live gateway answers it exits ("already running"), else it unlinks the stale file and binds. |
| `-P` | `0` | DTR polarity for safe state (0=low-active→safe=high). |
| `-R` | `0` | RTS polarity for safe state. |
| `--send-crlf` | off | Append `\r\n` to `SEND` text. |
| `--daemon` | off | Detach into background. |
| `-l` | `stderr` | Lifecycle log destination. |

`STATUS` keys (exact): `port`, `baud`, `open` (0/1), `uptime_s`, `clients`,
`controller` (client id or `none`), `rx_bytes`, `tx_bytes`, `buf_used`,
`safe_dtr`, `safe_rts`.

Signal handling: `SIGINT`/`SIGTERM` → restore safe state, clear `TIOCEXCL`,
close fd, remove socket. No DTR drop on exit (`HUPCL=0`).

> **Safe-state misconfiguration warning.** The safe DTR/RTS levels depend on the
> target's reset/boot circuit, which the gateway cannot discover. If `-P`/`-R`
> polarity is set wrong, the gateway may hold the target in permanent reset or
> force boot mode. Always confirm with `GET_MODEM` (and, if possible, observe the
> target) before relying on the gateway. Defaults assume an active-low circuit
> (safe = both lines high).

---

## 6. Invariants (must hold in every implementation)

1. Serial port `open()`ed **exactly once** at gateway start; all access via socket.
2. `ioctl(TIOCEXCL)` + `flock(LOCK_EX)` held for gateway lifetime → nothing else
   can open the port → no operational open-time reset.
3. `HUPCL=0` → gateway release/exit does not drop DTR → no reset on release.
4. DTR/RTS held in safe state by default; client connect/disconnect never moves
   them. (Any deliberate modem action, if ever added, is explicit and user-initiated.)
5. The **only** unavoidable modem pulse is the single `open()` at gateway launch
   (kernel/driver driven, verified against picocom source — see `DESIGN.md` §1);
   it is one-time and operator-initiated, and does **not** recur on client
   connect/disconnect. The guarantee is therefore "no reset on occupy/release",
   not "zero resets under all circumstances".
6. Clean-room: no picocom code copied/linked (GPL-2.0). `picocom-src` is a
   read-only reference submodule only.
7. Local Unix socket only. No TCP / remote transport.
8. Single controller enforced: only one client may `SEND`; others are monitors.
9. RX is buffered (§1.4) so `RECV` after `SEND` never races; subscribers are
   forward-only.
