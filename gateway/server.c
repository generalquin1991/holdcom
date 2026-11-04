/*
 * server.c - STUB (skeleton, no core logic yet)
 *
 * Intended implementation:
 *   - create a local Unix socket (bind sock_path, chmod 0600);
 *   - event loop (poll/select) over: serial fd, listen fd, client fds;
 *   - on serial RX: frame and broadcast to all subscriber clients;
 *   - on client RX: parse line protocol (see docs/PROTOCOL.md) and dispatch
 *     to serial_* helpers
 *     (SEND/RECV/RECV_UNTIL/GET_MODEM/STATUS/SUBSCRIBE/QUIT).
 *   - Client connect/disconnect NEVER touches the serial port's modem lines.
 */
#include "server.h"
#include <stdio.h>

int server_start(const server_cfg_t *cfg)
{
    (void)cfg;
    fprintf(stderr, "server_start: NOT IMPLEMENTED (skeleton)\n");
    return -1;
}
