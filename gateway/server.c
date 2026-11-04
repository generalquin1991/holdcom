/*
 * server.c - STUB (skeleton, no core logic yet)
 *
 * Intended implementation:
 *   - create Unix socket (bind sock_path, chmod 0600) and/or TCP listen on
 *     127.0.0.1:tcp_port;
 *   - event loop (poll/select) over: serial fd, listen fd, client fds;
 *   - on serial RX: frame and broadcast to all subscriber clients;
 *   - on client RX: parse line protocol (see docs/PROTOCOL.md) and dispatch
 *     to serial_* helpers (SEND/RECV/RECV_UNTIL/SET_DTR/SET_RTS/RESET/BOOT/STATUS/QUIT).
 */
#include "server.h"
#include <stdio.h>

int server_start(const server_cfg_t *cfg)
{
    (void)cfg;
    fprintf(stderr, "server_start: NOT IMPLEMENTED (skeleton)\n");
    return -1;
}
