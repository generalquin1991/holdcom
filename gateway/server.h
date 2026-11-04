/*
 * server.h - socket server & line protocol (skeleton, no logic yet)
 *
 * Transport: Unix domain socket (default) + optional 127.0.0.1 TCP.
 * The server owns the event loop over [serial fd, listen socket, clients].
 * AI clients talk ONLY to this server; they never open the serial port.
 */
#ifndef SERVER_H
#define SERVER_H

#include "serial.h"

typedef struct {
    serial_t *ser;
    char     *sock_path;   /* Unix socket path, NULL to disable */
    int       tcp_port;    /* 0 = disabled, else 127.0.0.1:tcp_port */
} server_cfg_t;

/* Start serving. Blocks in the event loop until shutdown. */
int server_start(const server_cfg_t *cfg);

#endif /* SERVER_H */
