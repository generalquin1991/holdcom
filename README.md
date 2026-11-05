# holdcom

Minimal, on-demand serial-port take-over that **never resets the MCU** on
take-over or release. A picocom-like tool that is also *programmatically
drivable* by both humans and AI.

## Why

`pyserial` re-opens the port and flips / drops the flow-control lines
(DTR/RTS), which resets boards such as the ESP32. `picocom` solves this with
`--noinit` + `--noreset`, but it is an interactive TTY with no programmatic
interface — awkward for an AI agent to drive.

`holdcom` borrows picocom's termios/ioctl mechanism
(`O_NOCTTY | O_NONBLOCK`, `HUPCL=0`, `TIOCEXCL`) and exposes it both as a
**CLI** and as a **library**, with a default that issues **zero**
modem-control ioctls.

## Install

### pip (Python)

```bash
pip install holdcom
```

### bash one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/generalquin1991/holdcom/main/install.sh | bash
```

### Homebrew (published tap)

```bash
brew tap generalquin1991/tap
brew trust generalquin1991/tap   # required ONCE for 3rd-party taps on brew 4.x
brew install holdcom
```

`holdcom` is a pure-stdlib script; the formula declares **no** Python
dependency, so it runs with whatever `python3` is already on your PATH
(macOS built-in, Homebrew, or user-installed). On brew 4.x a third-party tap
must be `trust`ed before its formulae can install — `brew install` will fail
with `sandbox_apply: Operation not permitted` until you do.

## Usage

The device may be given as a **positional** argument (picocom-style) or via
`-p`. No subcommand = interactive console (like picocom):

```bash
holdcom /dev/cu.usbmodem1101 -b 115200
holdcom -p /dev/cu.usbmodem1101 -b 115200      # equivalent
```

Inside the console: type to send, **Ctrl-]** to release and quit.

Programmatic subcommands (for AI / scripts):

```bash
holdcom -p /dev/ttyUSB0 -b 115200 send "AT\r\n"
holdcom -p /dev/ttyUSB0 recv -t 2
holdcom -p /dev/ttyUSB0 recv-until "OK" -t 5
holdcom -p /dev/ttyUSB0 status
holdcom selftest
```

> Note: when using a subcommand, place options (`-p`/`-b`) **before** the
> subcommand name — that is how argparse scopes them to `holdcom` itself.

## The no-reset guarantee

- **Take-over** (`open`): by default `holdcom` issues **no** modem-control
  ioctl at all — it leaves the kernel's post-`open()` line state untouched.
  The only unavoidable flow-control event is the kernel driver asserting
  DTR/RTS on `open()`, which is a hardware/OS fact, not something this tool
  does.
- **Release** (`close`): `HUPCL` is cleared (`--noreset` semantics), so
  closing the port does **not** drop DTR/RTS.
- **Optional idle level**: `--idle-dtr` / `--idle-rts` set DTR/RTS exactly
  once at take-over, for boards whose reset circuit needs a specific idle
  level. **Idle polarity is board-specific** — there is no "high is always
  safe". Leave them unset unless you have verified your board needs them.

The invariant "no modem-line touch except the optional one-time idle set at
take-over" is enforced by `holdcom selftest`, which AST-scans every function
and fails if any `TIOCM*` ioctl appears outside `set_idle_state`.

## Requirements

- Python 3.8+ (standard library only; no third-party dependencies).
- Linux and macOS.

## License

MIT — see [LICENSE](LICENSE).
