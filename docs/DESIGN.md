# Design: ai-serial-gateway

## 1. Problem (root cause, verified against picocom source)

A target MCU's auto-reset / auto-boot circuit (e.g. ESP32) wires the USB-UART
bridge's **RTS → EN (reset, active-low)** and **DTR → IO0 (boot select,
active-low)** through transistors. On Linux/macOS, `open()` of a USB-UART port
makes the kernel driver (`ftdi_sio` etc.) call `ftdi_dtr_rts(on=1)` → it
**asserts TIOCM_DTR/RTS** (`picocom-src/lowerrts.md:84-87`). That pulse resets /
boots the chip.

picocom documents this and can only *mitigate* it: `--lower-rts` lowers RTS
ASAP after open (still a 50–450 µs pulse, OS may preempt between open and
lower), and `--noreset` clears `HUPCL` so close does not drop DTR
(`picocom.c:2094`, `term.c:1214`). See `picocom-src/term.c`:
`term_set(..., local=1, hup_close=!noreset)`, `term_raise/lower_dtr/rts`
(ioctl `TIOCMBIS/TIOCMBIC`), `term_get_mctl` (ioctl `TIOCMGET`).

**pyserial triggers the pulse on *every* `open()`** → each interaction reboots
the MCU. That is the exact pain point.

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
      target MCU
```

AI never opens the serial port. The gateway opens it **once**, holds it
**exclusively**, and exposes a socket API. **Occupy = connect, release =
disconnect** — neither opens/closes the port, so neither affects DTR/RTS.

## 3. Guarantees (how resets on connect/disconnect are eliminated)

| # | Mechanism | Effect |
|---|----------|--------|
| 1 | Port `open()`ed once at startup; all access via socket | zero operational opens → zero operational resets |
| 2 | `ioctl(TIOCEXCL)` + `flock(LOCK_EX)` | nothing else can open the port |
| 3 | `HUPCL=0` | gateway release/exit does not drop DTR → no reset on release |
| 4 | DTR/RTS held in safe state; client connect/disconnect never moves them | no accidental trigger |
| 5 | On USB replug, gateway re-opens and re-asserts safe state | recovery stays exclusive |

The only unavoidable pulse is the single `open()` at gateway launch (kernel-
driven, see §1). It is a one-time, user-controlled event. The guarantee is
"no reset on connect/disconnect", **not** "zero resets under all circumstances":
the launch open itself pulses once. This is documented explicitly in
[`INTERFACE.md`](./INTERFACE.md) §1 and §6.

## 4. Implementation plan (modules + order)

Modules:

- `gateway/serial.{c,h}` — port ownership & modem lines. **Clean-room**:
  implements termios + `ioctl(TIOCMBIS/TIOCMBIC/TIOCMGET/TIOCEXCL)` ourselves,
  NOT copied from picocom.
- `gateway/server.{c,h}` — socket server, event loop, protocol dispatch,
  RX buffering + broadcast (binary-safe), single-controller enforcement,
  hotplug detection, stale-socket handling, logging.
- `gateway/main.c` — arg parsing, glue, signal handling.
- `client/uart_client.py` — pure-socket client (no pyserial).
- `client/cli.py` — CLI wrapper (+ `attach` interactive console).
- `docs/INTERFACE.md` — frozen interface contract (wire + C API + Python API +
  CLI + config).
- `docs/PROTOCOL.md` — wire-protocol deep-dive (mirrors `INTERFACE.md` §1).
- `docs/PLAN.md` — **risk-first, ordered** implementation plan with per-phase
  exit criteria (Phase 0 proves the modem guarantee before any UI is built).

The detailed, dependency-ordered build sequence (Phase 0 → 5) is in
[`PLAN.md`](./PLAN.md).

## 5. License decision (picocom is GPL-2.0)

picocom (`picocom-src/LICENSE.txt`) is **GPL-2.0**. We therefore:

- **Do NOT copy/link picocom code** into this repo. `serial.c` is a clean-room
  reimplementation using only the *approach* documented in picocom's `term.c` /
  `lowerrts.md` as reference.
- Keep `picocom-src` as a **read-only reference submodule**, pinned to a tag
  (e.g. `v3.1`) rather than floating `main`.
- **No fork needed.** We never consume picocom's code, so its upstream evolution
  has zero impact. To refresh: `git submodule update --remote picocom-src`. A
  fork is warranted only to upstream a patch to picocom itself, or if we
  abandoned clean-room and vendored a *modified* picocom (would reintroduce
  GPL — explicitly avoided).

## 6. Acceptance criteria

"Done" is defined by these checks. **Execution of any check that touches a real
USB-UART adapter or target MCU is deferred until explicitly permitted**; the
procedure is specified now so it can be run unchanged later.

1. **No modem movement on occupy/release.** With a real USB-UART adapter, a second
   observer process samples `TIOCMGET` DTR/RTS while a client connects and
   disconnects 100×. Assert: DTR/RTS unchanged across every transition.
   *Hardware-free proxy:* `strace -e ioctl` the gateway during 100 client
   connect/disconnect cycles; assert no `TIOCMSET`/`TIOCMBIS`/`TIOCMBIC` touching
   modem bits occurs. This can run without permission.
2. **Single launch pulse only.** Observer samples DTR/RTS across gateway start.
   Assert: exactly one assertion pulse at `open()`, then stable at safe state;
   no further pulses during the session.
3. **Byte-faithful loopback.** Echo server on the port; client `SEND`/`RECV`
   round-trip returns identical bytes (incl. binary) — validates `DATA`/`DATAHEX`
   and binary-safe `RX` broadcast.
4. **Console.** `uart-cli attach` shows live output and forwards keystrokes
   (incl. Ctrl-C via `SENDHEX`); Ctrl-] detaches; port not reset after detach.
5. **Hotplug.** Unplug + replug the adapter while gateway runs: gateway detects
   loss, holds safe state, rejects client I/O meanwhile, re-opens and re-asserts
   safe state on replug, still exclusive (`TIOCEXCL`).
6. **Exclusivity.** A `pyserial`/any process cannot `open()` the port while the
   gateway holds it (assert open fails with EBUSY).

Checks 3–6 can be partially exercised with a pty loopback for logic, but the
modem-line assertions (1, 2, 6) require a real adapter and are gated on
permission. Check 1's `strace` proxy needs no hardware.

## 7. Status

Skeleton only. Directory layout, Makefile, headers, interface/design/plan docs
are in place. **Core logic (serial termios/ioctl, socket event loop, protocol
parser, client implementation) is NOT yet written.** Real-device testing
deferred until explicitly permitted. The interface contract is frozen in
[`INTERFACE.md`](./INTERFACE.md) (minimal scope — flash / deliberate modem
commands removed as out of scope).
