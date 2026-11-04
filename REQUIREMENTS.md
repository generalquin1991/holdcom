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
3. **接管**：`open(O_NOCTTY|O_NONBLOCK)`。接管瞬间**一次性**把 DTR/RTS 设到
   "空闲安全态"——默认两者高（对常见的低有效复位电路 = 释放 = 安全）；
   非标准极性可用 `--idle-dtr` / `--idle-rts` 改成 low。这是唯一触碰 modem 线的
   时机（对齐 picocom 在 `tcsetattr` 之后调用 `set_dtr_rts()` 的做法，
   因为 `term_apply` 在某些驱动上会重置 DTR/RTS）。
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
- 实机测试（等你许可且开发完成后）

## 已拍板：AI 如何够到工具
- **(a) CLI / 库，按需调用**：人和 AI 都按需调用（AI 直接 shell 出去或 import 库）。
  不引入常驻 socket server、不做 daemon、不共享端口。
  理由：最简单、最贴合"想接管就接管、用完释放、全程不复位"；
  AI 侧只需 spawn 进程或 import，无需任何常驻中间层。

## 已拍板：空闲安全态（决策 B）
- 在 `open_safe` 末尾、`tcsetattr` 之后调用 `set_idle_state()`，一次性用
  `TIOCMBIS`/`TIOCMBIC` 设定 DTR/RTS 空闲电平；仅影响 DTR/RTS，不碰其它 modem 位。
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
