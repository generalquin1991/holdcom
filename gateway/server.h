/*
 * server.h - socket server & line protocol (skeleton, no logic yet)
 *
 * Transport: a single local Unix domain socket.
 * The server owns the event loop over [serial fd, listen socket, clients].
 * AI clients talk ONLY to this server; they never open the serial port.
 */
#ifndef SERVER_H
#define SERVER_H

#include "serial.h"

typedef struct {
    serial_t *ser;
    char     *sock_path;   /* local Unix socket path */
} server_cfg_t;

/* Start serving. Blocks in the event loop until shutdown. */
int server_start(const server_cfg_t *cfg);

#endif /* SERVER_H */
