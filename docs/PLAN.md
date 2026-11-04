# Implementation Plan (risk-first, ordered)

Principle: **prove the risky core first, then a thin vertical slice, then harden.**
The single risk that invalidates the whole project is the modem-line guarantee:
if `serial_open` + the gateway lifecycle cannot keep DTR/RTS stable across
client connect/disconnect, every other feature is worthless. So **Phase 0
de-risks that before any socket/server work**. Then we get one end-to-end byte
path working on a pty (no modem lines involved), then layer buffering /
broadcast / console, then robustness, then — gated on permission — real-device
acceptance.

Each phase has explicit **exit criteria**. A phase is "done" only when its exit
criteria pass. Real-device checks are deferred to Phase 5 per the user's rule
(no real-hardware testing until explicitly permitted).

## Phase 0 — Serial primitive + guarantee self-test (C, no socket)

- Implement `serial_open / serial_close / serial_get_modem / serial_read /
  serial_write` in `serial.c` (clean-room termios + `ioctl`; no picocom code).
- Apply, in order, at open: `O_RDWR|O_NOCTTY|O_NONBLOCK` → `ioctl(TIOCEXCL)` →
  `flock(LOCK_EX)` → `cfmakeraw` → set speed → `CLOCAL` → **clear `HUPCL`** →
  assert safe DTR/RTS via `TIOCMBIS/TIOCMBIC` → read back with `TIOCMGET` to
  confirm.
- **Exit criteria (hardware-free):**
  - Compiles cleanly on macOS and Linux.
  - A self-test opens a pty master as the pretend "device", calls `serial_open`,
    then simulates N client connect/disconnect cycles by invoking the internal
    state machine (no real socket yet). It asserts, via `strace -e ioctl` (or an
    `LD_PRELOAD` ioctl spy), that **after the initial safe-state assert, no
    further `TIOCMSET`/`TIOCMBIS`/`TIOCMBIC` touching modem bits occurs** during
    the cycles, and that `TIOCEXCL` + `HUPCL=0` are set. This proves the core
    invariant without any real MCU.
- Depends on: nothing.

## Phase 1 — Thin vertical slice: socket + SEND/RECV over pty

- `server.c`: `poll()` loop over `[listen fd, client fds]`; implement only
  `SEND`, `RECV`, `STATUS`, `PING`, `QUIT`. No broadcast yet.
- `uart_client.py`: `connect / send / send_hex / recv / recv_hex / recv_until /
  status / close`.
- **Exit criteria:** gateway pointed at a pty; a Python client connects, `SEND`s
  bytes; a loopback reader on the pty master echoes them back; client `RECV`s
  identical bytes. Proves the plumbing (the modem guarantee was already proven
  in Phase 0).
- Depends on: Phase 0.

## Phase 2 — RX buffering + binary-safe broadcast

- Gateway keeps a ring buffer of all RX bytes (default 64 KiB). `RECV` /
  `RECV_HEX` / `RECV_UNTIL` drain from this buffer, so a reader that calls
  `RECV` *after* the response arrived still gets it (no send→recv race).
  `SUBSCRIBE` is forward-only (bytes received after subscription).
- Broadcast frames: `RX <len>\n<bytes>` and `RXHEX <hex>` (see `INTERFACE.md`
  §1.3/§1.4). On overflow, drop oldest + emit `EVENT OVERFLOW`.
- **Exit criteria:** controller `SEND`s, response buffered; a late `RECV` still
  retrieves it; two subscribers both receive every frame in order.
- Depends on: Phase 1.

## Phase 3 — Console client (`attach`)

- `cli.py attach`: put local terminal in raw/cbreak, `SUBSCRIBE`, forward each
  keystroke via `SEND`/`SENDHEX` (Ctrl-C → `SENDHEX 03`), Ctrl-] → `UNSUBSCRIBE`
  + `QUIT`. Client ignores SIGINT for detaching; only the escape key ends it.
- **Exit criteria:** an interactive session shows live output, forwards
  keystrokes (incl. control chars), and detaches without resetting the target.
- Depends on: Phase 2.

## Phase 4 — Robustness & lifecycle

- **Single-controller enforcement + `BUSY`** (slot model in `INTERFACE.md` §1.5).
- **Stale socket cleanup** on start (probe existing socket; if alive → error
  "already running"; else unlink and bind). Socket `chmod 0600`.
- **Logging** of lifecycle events to `-l <logfile>` or stderr (start, client
  connect/disconnect, controller grant/release, `PORT_LOST`/`RESTORED`, errors).
- **Graceful startup when port absent**: if `-p` does not exist yet, start and
  wait for hotplug rather than failing.
- **Hotplug**: `PORT_LOST` / `PORT_RESTORED`; hold safe state and reject client
  I/O while lost; on restore re-open and re-assert safe state, still exclusive.
- **macOS device**: open the `/dev/cu.*` callout device (not `/dev/tty.*`, which
  can trigger getty/dialin handling).
- **Exit criteria:** killing the gateway removes the socket; a second controller
  `SEND` gets `BUSY`; unplug → `PORT_LOST`, replug → `PORT_RESTORED` and still
  exclusive; starting a second gateway on the same socket errors out.
- Depends on: Phase 2 (controller) and Phase 0 (hotplug re-open).

## Phase 5 — Acceptance (gated on user permission)

- Real USB-UART adapter: observer samples `TIOCMGET` DTR/RTS across 100
  connect/disconnect cycles → unchanged.
- Launch pulse: confirm exactly one assertion at `open()`, then stable.
- Exclusivity: a `pyserial`/any process cannot `open()` the port while the
  gateway holds it (open fails with `EBUSY`).
- Full list in `DESIGN.md` §6.
- Depends on: all above.

## Why this order

1. **Phase 0 first** — it is the only thing that can kill the project; if it
   fails we pivot before building any UI or protocol.
2. **Slice (1) before breadth (2, 3)** — a working byte path exists to test
   against before we add buffering and console.
3. **Robustness (4) last among code** — it does not affect the core proof and is
   where most churn happens; deferring it keeps the risky proof front and center.
4. **Real-device (5) is explicitly last and permission-gated**, per the user's
   standing rule.
