# Design: ai-serial-gateway

## 1. Problem (root cause, verified against picocom source)

ESP32's auto-reset / auto-boot circuit wires the USB-UART bridge's
**RTS → EN (reset, active-low)** and **DTR → IO0 (boot select, active-low)**
through transistors. On Linux/macOS, `open()` of a USB-UART port makes the
kernel driver (`ftdi_sio` etc.) call `ftdi_dtr_rts(on=1)` → it **asserts
TIOCM_DTR/RTS** (`picocom-src/lowerrts.md:84-87`). That pulse resets / boots
the chip.

picocom documents this and can only *mitigate* it: `--lower-rts` lowers RTS
ASAP after open (still a 50–450 µs pulse, OS may preempt between open and
lower), and `--noreset` clears `HUPCL` so close does not drop DTR
(`picocom.c:2094`, `term.c:1214`). See `picocom-src/term.c`:
`term_set(..., local=1, hup_close=!noreset)`, `term_raise/lower_dtr/rts`
(ioctl `TIOCMBIS/TIOCMBIC`), `term_get_mctl` (ioctl `TIOCMGET`).

**pyserial triggers the pulse on *every* `open()`** → each AI interaction
reboots the ESP32. That is the exact pain point.

## 2. Solution: long-lived exclusive gateway

```
 AI / script (Python client, plain socket, NO pyserial)
        │  local Unix socket
        ▼
 uart-gateway (C daemon)
   socket server → protocol parser → serial mgr
        │  open()×1, TIOCEXCL, HUPCL=0, DTR/RTS=safe
        ▼
 USB-UART bridge  (RTS→EN, DTR→IO0, active-low)
        ▼
      ESP32
```

AI never opens the serial port. The gateway opens it **once**, holds it
**exclusively**, and exposes a socket API.

## 3. Guarantees (how the reset is *fully* eliminated)

| # | Mechanism | Effect |
|---|----------|--------|
| 1 | Port `open()`ed once at startup; all AI access via socket | zero operational opens → zero operational resets |
| 2 | `ioctl(TIOCEXCL)` + `flock(LOCK_EX)` | pyserial (or anything) **cannot** open the port while gateway holds it |
| 3 | `HUPCL=0` (`local=1, hup_close=0`) | gateway exit does not drop DTR → no exit reset |
| 4 | DTR/RTS held in safe run state (ESP32: DTR=1,RTS=1) | no accidental trigger; only explicit `RESET`/`BOOT` moves them |
| 5 | On USB replug, gateway re-opens and re-asserts safe state | recovery stays exclusive; outside processes cannot interleave |

The only unavoidable pulse is the single `open()` at gateway launch
(kernel-driven, see §1). It is a one-time, user-controlled event.

## 4. Implementation plan (modules)

- `gateway/serial.{c,h}` — port ownership & modem lines. **Clean-room**:
  implements termios + `ioctl(TIOCMBIS/TIOCMBIC/TIOCMGET/TIOCEXCL)` ourselves,
  NOT copied from picocom.
- `gateway/server.{c,h}` — socket server, event loop, protocol dispatch,
  RX broadcast, multiple clients (1 controller + monitors).
- `gateway/main.c` — arg parsing, glue.
- `client/uart_client.py` — pure-socket client (no pyserial).
- `client/cli.py` — CLI wrapper.
- `docs/INTERFACE.md` — frozen interface contract (wire + C API + Python API + CLI + config).
- `docs/PROTOCOL.md` — wire-protocol deep-dive (mirrors `INTERFACE.md` §1).

## 5. License decision (picocom is GPL-2.0)

picocom (`picocom-src/LICENSE.txt`) is **GPL-2.0**. We therefore:

- **Do NOT copy/link picocom code** into this repo. `serial.c` is a
  clean-room reimplementation using only the *approach* documented in
  picocom's `term.c` / `lowerrts.md` as reference. This keeps our gateway
  code license-clean.
- Keep `picocom-src` as a **read-only reference submodule**, pinned to a tag
  (e.g. `v3.1`) rather than floating `main`, for reproducibility.
- **No fork needed.** Because we never consume picocom's code, its upstream
  evolution has zero impact on our build/behaviour. To refresh the reference:
  `git submodule update --remote picocom-src`. A fork is warranted only if we
  intend to upstream a patch to picocom itself (fork → branch → PR), or if we
  abandoned clean-room and vendored a *modified* picocom — the latter would
  reintroduce GPL, which we explicitly avoid.

## 6. Flash / yield mode (pty proxy) — design gap, now closed

A native flashing tool (e.g. `esptool`) must `open()` the port itself and toggle
DTR/RTS for the reset/boot sequence. But our invariant holds the real port
exclusively (`TIOCEXCL`), so the tool cannot open it — and even if we released
it, `open()` would itself emit the reset pulse. **Releasing the port is not a
solution.**

Design: the gateway **keeps** the real port and instead creates a **pty** for the
tool to use.

1. Client sends `FLASH_BEGIN`.
2. Gateway calls `posix_openpt` + `grantpt` + `unlockpt` to make a pty pair,
   starts a transparent bridge loop (**before** replying), then replies
   `FLASH_READY <slave_path>` (macOS `/dev/ttysNNN`, Linux `/dev/pts/N`).
3. Client launches the tool with `--port <slave_path>`. The tool `open()`s the
   **pty**, not the real device → no open-time pulse on hardware.
4. Bridge forwards bytes pty-master ↔ real serial fd and **mirrors modem
   ioctls** (`TIOCMGET/SET` on pty master → `TIOCMSET` on real port), so the
   tool's DTR/RTS reset sequence reaches the device faithfully.
5. Tool exits → client `FLASH_END` (or pty EOF). Gateway stops bridge, re-asserts
   safe DTR/RTS, closes pty, returns to normal mode.

Why this is correct: the real port is still `open()`ed exactly once; `TIOCEXCL`
is held throughout, so even the flashing tool cannot touch it directly. The tool
gets its intentional reset via the ioctl mirror; `HUPCL` on the real port stays
`0` regardless of what the tool sets on the pty, so tool exit does not drop DTR.
(An alternative — passing the real fd via `SCM_RIGHTS` — was rejected: the tool
would not know to return it, and `TIOCEXCL`/safe-state invariants would break.)

## 7. Status

Skeleton only. Directory layout, Makefile, headers, protocol/design docs, and
stub functions are in place. **Core logic (serial termios/ioctl, socket event
loop, protocol parser, client implementation) is NOT yet written.** Real-device
testing deferred until explicitly permitted. The interface contract is frozen in
[`INTERFACE.md`](./INTERFACE.md).
