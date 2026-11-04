# 需求（已冻结）

## 目标
做一个工具，让"人"和"AI"都能**按需接管**一个 USB 串口、用完**释放**；
接管与释放全过程**不碰流控线（DTR/RTS）**，因此不触发 MCU 复位。

## 出发点
- **以 picocom 为基准**：picocom 已用 `--noinit`（接管不动线）+ `--noreset`/Quit
  （`HUPCL=0`，关闭不掉 DTR/RTS）证明接管/释放可以不碰流控线。
  本工具的串口核心照此机制实现（termios + ioctl，`O_NOCTTY|O_NONBLOCK`，
  `HUPCL=0`，不开 `TIOCEXCL` 之外的多余操作）。
- **pyserial 是被替换的对象，不是基础**：pyserial 一接管就翻转/掉线导致复位，
  解决不了这个问题，所以不基于它开发。AI 侧接口也不走 pyserial。

## 必须做到的（已确认）
1. 人能用，AI 也能用。
2. 按需接管 / 释放；AI 不需要长期持有端口。
3. **接管**：`open(O_NOCTTY|O_NONBLOCK)`，不配置、不翻转任何 modem 线
   （`--noinit` 语义）。唯一会发生的流控事件是内核 `open()` 那次不可避免断言
   （硬件/驱动事实，非本工具所为）。
4. **释放**：关闭时 `HUPCL=0`（`--noreset` 语义），不掉 DTR/RTS。
5. 接口要**程序化**（AI 可驱动）+ 提供 **CLI**（人可用）。
   picocom 是交互式 TTY，本工具不是。

## 明确不做（避免过度设计）
- 长期持有 / 常驻 daemon
- 多客户端共享
- flash / pty 代理
- 主动控线（SET_DTR / SET_RTS / RESET / BOOT）
- TCP / 远程
- 实机测试（等你许可且开发完成后）

## 已拍板：AI 如何够到工具
- **(a) CLI / 库，按需调用**：人和 AI 都按需调用（AI 直接 shell 出去或 import 库）。
  不引入常驻 socket server、不做 daemon、不共享端口。
  理由：最简单、最贴合"想接管就接管、用完释放、全程不碰流控线"；
  AI 侧只需 spawn 进程或 import，无需任何常驻中间层。

## 交付约束
- 先只这一个文件锁定需求，再谈实现。
- 最小实现，不堆文件夹、不堆文件。
