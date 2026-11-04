# 需求（已冻结）

## 目标
做一个工具，让"人"和"AI"都能**按需接管**一个 USB 串口、用完**释放**；
接管与释放全过程**不触发 MCU 复位**。

## 出发点
- **以 picocom 为基准**：picocom 用 `--noinit`（不配置端口）+ `--noreset`/Quit
  （`HUPCL=0`，关闭不掉 DTR/RTS）证明接管/释放可以做到不复位。
  本工具的串口核心照此机制实现（termios + ioctl，`O_NOCTTY|O_NONBLOCK`，
  `HUPCL=0`，`TIOCEXCL` 单持有）。
- **pyserial 是被替换的对象，不是基础**：pyserial 一接管就翻转/掉线导致复位，
  解决不了这个问题，所以不基于它开发。AI 侧接口也不走 pyserial。

## 必须做到的（已确认）
1. 人能用，AI 也能用。
2. 按需接管 / 释放；AI 不需要长期持有端口。
3. **接管**：`open(O_NOCTTY|O_NONBLOCK)`。**默认不发出任何 modem 线操作**，
   完全保留内核 `open()` 之后的默认线态——这是"不碰流控线"最严格的实现，也是
   实机验证过的普遍安全默认（见"实测记录"）。
   仅在用户显式传 `--idle-dtr` / `--idle-rts` 时，才在 `tcsetattr` 之后**一次性**
   用 `TIOCMBIS`/`TIOCMBIC` 把 DTR/RTS 设到指定空闲电平（对齐 picocom 在
   `term_apply` 之后调 `set_dtr_rts()`，因 `term_apply` 在某些驱动上会重置
   DTR/RTS）。**空闲极性是板子相关的，没有"high 必安全"的普适结论**——设错反而
   会把 MCU 复位，故默认不放任何一档。
   唯一由内核驱动的、不可避免的 `open()` 断言脉冲（硬件/OS 事实）仍会发生，
   非本工具所为。
4. **释放**：关闭时 `HUPCL=0`（`--noreset` 语义），不掉 DTR/RTS；释放与所有
   收发操作**绝不**触碰 modem 线。
5. 接口要**程序化**（AI 可驱动）+ 提供 **CLI**（人可用）。
   picocom 是交互式 TTY，本工具不是。

## 明确不做（避免过度设计）
- 长期持有 / 常驻 daemon
- 多客户端共享
- flash / pty 代理
- 主动控线（SET_DTR / SET_RTS / RESET / BOOT）
  注意：仅"接管时的空闲安全态一次性设定"是允许的，见上 3；除此之外任何主动控线都禁止。
- TCP / 远程
- 实机测试：已于 2026-11-05 在真实 ESP32-S3（原生 USB `/dev/cu.usbmodem1101`）
  完成，仅验证"不复位"，**未烧录**。

## 已拍板：AI 如何够到工具
- **(a) CLI / 库，按需调用**：人和 AI 都按需调用（AI 直接 shell 出去或 import 库）。
  不引入常驻 socket server、不做 daemon、不共享端口。
  理由：最简单、最贴合"想接管就接管、用完释放、全程不复位"；
  AI 侧只需 spawn 进程或 import，无需任何常驻中间层。

## 已拍板：空闲安全态（决策 B，已按实机修正）
- **默认零触碰**：`open_safe` 默认**不调用** `set_idle_state()`，即不发出任何
  `TIOCMBIS`/`TIOCMBIC`，完全保留内核 `open()` 后的默认线态。这是"不碰流控线"
  的最严格实现，也是实机验证过的普遍安全默认（见"实测记录"）。
- **可选覆盖**：仅当用户显式传 `--idle-dtr` / `--idle-rts` 时，`set_idle_state()`
  才在 `tcsetattr` 之后**一次性**用 `TIOCMBIS`/`TIOCMBIC` 设定 DTR/RTS 电平；
  仅影响 DTR/RTS，不碰其它 modem 位。
- 静态自检（`selftest`）通过 AST 逐函数扫描，强制 `TIOCM*` 只允许出现在
  `set_idle_state`（及其调用点 `open_safe`），其余函数一律不得出现——
  保证"释放/收发绝不碰流控线"这一不变量可被机器验证。

## picocom 子仓库
- `picocom/` 作为 **git submodule** 引入，**仅作参考阅读**，不编译、不链接、
  不拷贝其代码，因此不会把 GPL-2.0 传染进本工具。
- 本工具的 `serial_takeover.py` 是 clean-room 实现，只借鉴 picocom 的 termios/ioctl
  思路与行为语义（--noinit / --noreset / 接管后设空闲态），不复制代码。

## 交付约束
- 先只这一个文件锁定需求，再谈实现。
- 最小实现，不堆文件夹、不堆文件。

## 实测记录（2026-11-05，真实 ESP32-S3，原生 USB `/dev/cu.usbmodem1101`，未烧录）
- **修复**：`termios.cfsetspeed` 在 macOS 不存在（Linux-only），传 `-b` 设波特率会
  崩；改为跨平台直接写 `tcgetattr` 返回的 ispeed/ospeed 字段（列表索引 4/5）。
- **结论：空闲极性是板子相关的，没有"high 必安全"**。同一块 ESP32-S3 实测：
  - 默认（不碰线，内核默认双断言 `0x0006`）：**无复位**，读到运行中 app 日志。
  - `--idle-dtr low --idle-rts high`（`0x0004`）：**触发复位**，串口打出
    `ESP-ROM…rst:0x15 (USB_UART_CHIP_RESET)`，进 bootloader——证明某些 DTR/RTS
    组合确实会复位，故默认必须"零触碰"而非"默认 high"。
  - `--idle-rts low`（`0x0002`）：无复位签名。
- **接管/释放循环无复位（close 不掉线，已实机闭合）**：
  之前"close 不掉 DTR/RTS"仅代码层由 `HUPCL=0` 保证、未实机验证，现已闭合。
  用 `console` 子命令对同一端口连续做了 **3 次 attach→release** 循环（仅读运行中
  app 日志，无任何写操作、无 `TIOCM*` 翻转、未烧录）。关键证据是目标固件日志的
  自启动毫秒计时器 `I (N)` 全程**单调递增、零归零**：
  - 第 1 段 release 前最后读到 `I (5062)`
  - 第 2 段 attach 后首行 `I (323406)` —— 与第 1 段连续，说明 release 未复位
  - 第 3 段 attach 后首行 `I (331943)` —— 与第 2 段连续，说明第 2 段 release 也未复位
  若 `close()` 因未清 `HUPCL` 而掉 DTR/RTS（复位沿），或 `open()` 的断言脉冲触发复位，
  `N` 必在某次 attach/release 归零；三次循环全连续 → 直接证明：
  (1) attach 不复位（内核 open 默认线态在本驱动不构成复位沿）；
  (2) release 不复位（`HUPCL=0` 生效，close 不掉线）。
- **验证方法**（未落盘，按需复用）：对每种 idle 配置执行
  `open_safe → TIOCMGET 读线态 → 3s 收数 → 扫描复位签名（ESP-ROM / rst:0x /
  boot: 等）→ close_safe`；`selftest` 静态扫描仍通过（TIOCM 仅在 `set_idle_state`，
  默认 no-op）。
