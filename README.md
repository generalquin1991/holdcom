# ai-serial-gateway

A long-lived, **exclusive** serial-port gateway so that AI / scripts can talk
to a UART device **without rebooting it on every connect**.

## Why this exists

`pyserial` calls `open()` on the USB-UART port for every session. On
Linux/macOS that makes the kernel driver assert `DTR`/`RTS`, which — through
a target MCU's auto-reset circuit (e.g. RTS→EN, DTR→IO0, active-low) —
**resets the chip on every connect**. This project removes the serial port from
the AI critical path entirely.

## How it works

```
 AI/client (plain socket, NO pyserial)  ──►  uart-gateway (C daemon)
                                                  │ open()×1
                                                  │ TIOCEXCL + flock (exclusive)
                                                  │ HUPCL=0, DTR/RTS = safe run state
                                                  ▼
                                            USB-UART bridge ──► target MCU
```

The gateway opens the port **once**, holds it **exclusively**
(`TIOCEXCL` + `flock`), and never drops `DTR` on exit (`HUPCL=0`). AI tools
connect over a local Unix socket and never touch the port.

**Occupy = connect, release = disconnect** — neither opens/closes the port, so
neither affects DTR/RTS and neither resets the MCU.

See `docs/DESIGN.md`, `docs/PROTOCOL.md`, and the frozen `docs/INTERFACE.md`.

## Scope (frozen)

Minimal, explicit scope: a reliable entry point whose occupy/release never
affects DTR/RTS, usable both programmatically (AI/scripts) and interactively
(`uart-cli attach` console). Flash / yield (pty proxy) mode and deliberate
modem-write commands (`SET_DTR`/`SET_RTS`/`RESET`/`BOOT`) are **out of scope**
unless explicitly requested.

## Status: SKELETON

Structure, Makefile, headers, docs and stub functions are present.
**Core logic is not implemented yet.** Real-device testing is deferred until
explicitly approved.

## Build (skeleton)

```bash
cd gateway && make        # builds the stub uart-gateway binary
```

## Layout

```
ai-serial-gateway/
├── picocom-src/          # reference submodule (GPL-2.0, NOT copied)
├── gateway/              # C daemon (serial.c / server.c / main.c / Makefile)
├── client/               # Python pure-socket client + CLI (no pyserial)
└── docs/                 # DESIGN.md, PROTOCOL.md, INTERFACE.md
```
