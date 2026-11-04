# ai-serial-gateway

A long-lived, **exclusive** serial-port gateway so that AI / scripts can talk
to an ESP32 (or any UART device) **without rebooting it**.

## Why this exists

`pyserial` calls `open()` on the USB-UART port for every session. On
Linux/macOS that makes the kernel driver assert `DTR`/`RTS`, which — through
ESP32's auto-reset circuit (RTS→EN, DTR→IO0, active-low) — **resets the
chip on every connect**. This project removes the serial port from the
AI critical path entirely.

## How it works

```
 AI/client (plain socket, NO pyserial)  ──►  uart-gateway (C daemon)
                                                  │ open()×1
                                                  │ TIOCEXCL + flock (exclusive)
                                                  │ HUPCL=0, DTR/RTS = safe run state
                                                  ▼
                                            USB-UART bridge ──► ESP32
```

The gateway opens the port **once**, holds it **exclusively**
(`TIOCEXCL` + `flock`), and never drops `DTR` on exit (`HUPCL=0`). AI tools
connect over a Unix socket (or `127.0.0.1` TCP) and never touch the port.
See `docs/DESIGN.md` and `docs/PROTOCOL.md`.

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
└── docs/                 # DESIGN.md, PROTOCOL.md
```
