# Interface Contract (frozen)

This document is the **authoritative, frozen interface specification** for
`ai-serial-gateway`. It covers every interface surface the tool exposes:

1. Wire protocol (client ↔ gateway, Unix socket) — also mirrored in `PROTOCOL.md`.
2. C API (`serial.h` / `server.h`).
3. Python client API (`client/uart_client.py`).
4. CLI surface (`client/cli.py`).
5. Gateway startup / configuration interface.

This is a **generic** serial-takeover tool. No specific target hardware,
project, or personal context is assumed. The "reset on open" problem is the
only motivating scenario; the interfaces are device-agnostic.

---

## 1. Wire protocol (client ↔ gateway)

Transport: **local Unix domain socket** only (default `/tmp/uart-gateway.sock`).
Framing: every request/reply is `\n`-terminated (LF). Binary is carried either
as a length-framed block or as hex on a single line (see `DATA` / `DATAHEX`).

One client acts as the **controller** (may send); others may **subscribe** as
**monitors** (RX broadcast only). The gateway holds the serial port exclusively
(`TIOCEXCL` + `flock`); clients never open it.

### 1.1 Client → Gateway commands

| Command | Args | Purpose |
|---------|------|---------|
| `SEND <text>` | text (no embedded LF) | Transmit text; whether a trailing `\r\n` is added is controlled by config (`send-crlf`). |
| `SENDHEX <hex>` | even-length hex string | Transmit raw bytes (AI-safe; no framing issues). |
| `RECV <timeout_ms>` | integer ms | Read whatever bytes are available within timeout → `DATA` frame. |
| `RECV_UNTIL <pattern> <timeout_ms>` | text pattern, ms | Block until `<pattern>` appears in the RX stream or timeout. |
| `RECV_HEX <timeout_ms>` | integer ms | Like `RECV`, but reply is `DATAHEX <hex>` (single line, AI-friendly). |
| `SET_DTR <0\|1>` | 0 or 1 | Assert (1) / deassert (0) DTR **after polarity mapping**. |
| `SET_RTS <0\|1>` | 0 or 1 | Assert (1) / deassert (0) RTS **after polarity mapping**. |
| `GET_MODEM` | — | Reply with current modem line states (post-polarity). |
| `RESET` | — | Perform a reset pulse sequence (polarity/timing from config). |
| `BOOT` | — | Perform the bootloader-entry sequence (DTR/RTS dance; e.g. esptool-style). |
| `STATUS` | — | Report port / baud / DTR / RTS / open state / uptime. |
| `SUBSCRIBE` | — | Register this client as an RX broadcast subscriber. |
| `UNSUBSCRIBE` | — | Cancel RX subscription. |
| `FLASH_BEGIN` | — | Enter flash mode → gateway creates a pty and replies `FLASH_READY <slave_path>`. |
| `FLASH_END` | — | Exit flash mode → gateway stops the pty bridge, re-asserts safe state. |
| `PING` | — | Health check → `PONG`. |
| `QUIT` | — | Close this client connection. |
| `SHUTDOWN` | — | Stop the gateway (admin; optional). |

### 1.2 Gateway → Client replies

| Reply | Meaning |
|-------|---------|
| `OK` | Command accepted. |
| `ERR <reason>` | Command failed (with human-readable reason). |
| `DATA <len>` | Header line; followed by exactly `<len>` raw bytes, then a trailing LF. Client switches to "read N bytes" mode after the header. |
| `DATAHEX <hex>` | Single-line hex-encoded received bytes (AI-friendly, no framing ambiguity). |
| `MODEM DTR=x RTS=x CTS=x DSR=x` | Modem line states, post-polarity (x ∈ {0,1}). |
| `STATUS <key=value ...>` | Status snapshot. |
| `FLASH_READY <slave_path>` | pty slave path for the flashing tool to open as its `--port`. |
| `BUSY` | Request cannot be served now (e.g. flash mode active, or another client holds the flash session). |
| `PONG` | Reply to `PING`. |
| `RX <line>` | Broadcast to subscribers: one received line (or framed block) from the serial port. |
| `EVENT <type>` | Async event, e.g. `EVENT DISCONNECT`, `EVENT RECONNECT`. |

### 1.3 Data framing rules

- `DATA <len>\n<bytes>\n`: `<len>` is a decimal byte count. The reader consumes
  exactly `<len>` bytes after the header line, then the terminating LF. Used
  when binary content may contain embedded LF.
- `DATAHEX <hex>\n`: the whole received buffer encoded as hex on one line.
  Preferred for AI consumers to avoid framing edge cases.
- `RECV_UNTIL` matches `<pattern>` as a substring in the accumulated RX buffer;
  the reply is the buffer up to and including the match (as `DATA`/`DATAHEX`).

### 1.4 Flash / yield mode (pty proxy)

This is the design gap that lets a native flashing tool (e.g. `esptool`) take
over the port **without triggering an open-time reset**.

1. Client sends `FLASH_BEGIN`.
2. Gateway creates a pty pair (`posix_openpt` + `grantpt` + `unlockpt`),
   starts a transparent bridge loop (**before** replying), then replies
   `FLASH_READY <slave_path>` where `<slave_path>` is the pty slave
   (`/dev/ttysNNN` on macOS, `/dev/pts/N` on Linux).
3. Client launches the flashing tool with `--port <slave_path>`. The tool
   `open()`s the **pty**, not the real device → no open-time pulse on hardware.
4. The bridge forwards bytes both ways (pty-master ↔ real serial fd) and
   **mirrors modem-control ioctls** (`TIOCMGET/SET` on the pty master →
   `TIOCMSET` on the real port), so the tool's DTR/RTS reset sequence reaches
   the device faithfully.
5. When the tool exits, client sends `FLASH_END` (or the pty master hits EOF).
   Gateway stops the bridge, re-asserts the safe DTR/RTS state, closes the pty,
   and returns to normal text-protocol mode.

During flash mode, the text protocol is **suspended**: other clients' commands
return `BUSY`. Only the controller that issued `FLASH_BEGIN` may send
`FLASH_END`.

---

## 2. C API (`gateway/serial.h`, `gateway/server.h`)

### 2.1 `serial.h`

```c
typedef struct serial serial_t;

typedef struct {
    int baud;          /* e.g. 115200 */
    int dtr_active;    /* 1 = high-active, 0 = low-active (default) */
    int rts_active;    /* 1 = high-active, 0 = low-active (default) */
    int reset_pulse_ms;/* width of the reset low-pulse */
    int boot_pulse_ms; /* width of the boot-select pulse */
} serial_cfg_t;

/* Open exactly once: O_RDWR|O_NOCTTY|O_NONBLOCK, TIOCEXCL, flock(LOCK_EX),
   cfmakeraw, set speed, CLOCAL, clear HUPCL, then assert safe DTR/RTS. */
serial_t *serial_open(const char *port, const serial_cfg_t *cfg);

/* Assert (on=1) / deassert (on=0) DTR or RTS, mapped through polarity. */
int serial_set_dtr(serial_t *s, int on);
int serial_set_rts(serial_t *s, int on);

/* Read current modem lines (post-polarity). Any pointer may be NULL. */
int serial_get_modem(serial_t *s, int *dtr, int *rts, int *cts, int *dsr);

/* Reset pulse sequence and bootloader-entry sequence (timing from cfg). */
int serial_reset(serial_t *s);
int serial_boot(serial_t *s);

/* Raw byte I/O. read() honours timeout_ms (0 = poll, -1 = block). */
ssize_t serial_write(serial_t *s, const void *buf, size_t n);
ssize_t serial_read(serial_t *s, void *buf, size_t n, int timeout_ms);

/* Restore safe state, clear TIOCEXCL, close fd. HUPCL=0 ⇒ no DTR drop. */
int serial_close(serial_t *s);
```

### 2.2 `server.h`

```c
typedef struct {
    serial_t   *ser;
    const char *sock_path;   /* Unix socket path; created with chmod 0600 */
} server_cfg_t;

/* Blocking: owns the poll() loop over [serial fd, listen fd, client fds],
   dispatches the wire protocol, broadcasts RX, and runs the flash pty bridge. */
int server_run(const server_cfg_t *cfg);
```

---

## 3. Python client API (`client/uart_client.py`)

```python
class UartGateway:
    def __init__(self, sock_path: str = "/tmp/uart-gateway.sock"): ...
    def connect(self) -> None: ...
    def send(self, text: str, newline: bool = True) -> None: ...
    def send_hex(self, hexstr: str) -> None: ...
    def recv(self, timeout_ms: int = 1000) -> bytes: ...
    def recv_until(self, pattern: str, timeout_ms: int = 5000) -> bytes: ...
    def recv_hex(self, timeout_ms: int = 1000) -> str: ...
    def set_dtr(self, on: bool) -> None: ...
    def set_rts(self, on: bool) -> None: ...
    def get_modem(self) -> dict: ...          # {"dtr":0/1,"rts":0/1,"cts":0/1,"dsr":0/1}
    def reset(self) -> None: ...
    def boot(self) -> None: ...
    def status(self) -> dict: ...
    def subscribe(self): ...                  # context manager yielding an RX iterator
    def flash(self, cmd: list[str], port_token: str = "AUTO") -> int:
        """FLASH_BEGIN -> parse FLASH_READY -> substitute port_token with the
        pty path in cmd -> run subprocess -> FLASH_END. Returns exit code."""
    def close(self) -> None: ...
```

Notes:
- `flash()` substitutes `port_token` (default `"AUTO"`) in the command list with
  the `FLASH_READY` pty path, so a caller writes
  `gw.flash(["esptool.py", "--port", "AUTO", "write_flash", ...])`.
- `subscribe()` blocks for `RX` broadcasts; ideal for log capture without
  disturbing a controller.

---

## 4. CLI surface (`client/cli.py`)

```
uart-cli send "AT\r\n"
uart-cli recv -t 1000
uart-cli recv-until "OK" -t 5000
uart-cli status
uart-cli reset
uart-cli boot
uart-cli flash -- esptool.py --port AUTO write_flash 0x1000 boot.bin
uart-cli attach            # interactive non-reset terminal (subscribe RX + forward stdin)
```

Subcommands map 1:1 onto the wire commands. `flash` wraps the Python
`flash()` helper; everything after `--` is the native flashing command with
`AUTO` replaced by the pty path.

---

## 5. Gateway startup / configuration interface

```
uart-gateway -p <port> -b <baud> -s <sock_path>
             [-P <dtr_polarity>] [-R <rts_polarity>]
             [--reset-ms <ms>] [--boot-ms <ms>]
             [--send-crlf] [--daemon]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `-p` | (required) | Serial device path, e.g. `/dev/cu.usbserial-XXXX`. |
| `-b` | `115200` | Baud rate. |
| `-s` | `/tmp/uart-gateway.sock` | Unix socket path. |
| `-P` | `0` | DTR polarity: `0`=low-active (safe=high), `1`=high-active. |
| `-R` | `0` | RTS polarity: `0`=low-active (safe=high), `1`=high-active. |
| `--reset-ms` | `100` | Reset low-pulse width. |
| `--boot-ms` | `50` | Boot-select pulse width. |
| `--send-crlf` | off | Append `\r\n` to `SEND` text. |
| `--daemon` | off | Detach into background. |

Signal handling: `SIGINT` / `SIGTERM` → restore safe state, clear `TIOCEXCL`,
close fd, remove socket. No DTR drop on exit (`HUPCL=0`).

---

## 6. Invariants (must hold in every implementation)

1. Serial port `open()`ed **exactly once** at gateway start. All AI/tool access
   is via the socket.
2. `ioctl(TIOCEXCL)` + `flock(LOCK_EX)` held for the gateway's whole lifetime →
   nothing else can open the port → no operational open-time reset.
3. `HUPCL=0` → gateway exit does not drop DTR → no exit reset.
4. DTR/RTS held in the safe run state; only explicit `RESET`/`BOOT`/flash
   sequence move them.
5. The only unavoidable pulse is the single `open()` at launch (kernel-driven).
   It is a one-time, user-controlled event.
6. Clean-room: no picocom code copied/linked (GPL-2.0). `picocom-src` is a
   read-only reference submodule only.
7. Local Unix socket only. No TCP / remote transport (removed by decision).
