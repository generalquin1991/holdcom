/*
 * serial.h - serial port ownership & safe-state (clean-room)
 *
 * Reference only: picocom's term.c / lowerrts.md (GPL-2.0, NOT copied).
 * No logic implemented yet; this is the interface skeleton.
 *
 * Scope (frozen, minimal): the gateway opens the port once and holds it
 * exclusively. It exposes send/receive and read-only modem status. Deliberate
 * modem-write commands (SET_DTR/SET_RTS/RESET/BOOT) and flash/yield mode are
 * OUT OF SCOPE unless explicitly requested later.
 */
#ifndef SERIAL_H
#define SERIAL_H

#include <stdbool.h>
#include <termios.h>
#include <sys/types.h>

typedef struct {
    int      fd;          /* serial fd, -1 when closed */
    char    *port;
    speed_t  baud;
    int      databits;
    int      stopbits;
    int      parity;
    bool     flow;
    bool     local;       /* CLOCAL */
    bool     hupcl;       /* HUPCL: we keep this false so close does not drop DTR */
    struct termios orig;
} serial_t;

/* lifecycle & config */
int  serial_open (serial_t *s, const char *port, speed_t baud);
void serial_close(serial_t *s);
int  serial_set_attr(serial_t *s, int databits, int stopbits, int parity, bool flow);

/* read-only modem status (post-polarity) */
int  serial_get_mctl(serial_t *s, int *dtr, int *rts, int *cts, int *dsr);

/* raw byte I/O (read honours timeout_ms: 0=poll, -1=block) */
ssize_t serial_write(serial_t *s, const void *buf, size_t n);
ssize_t serial_read (serial_t *s, void *buf, size_t n, int timeout_ms);

/* internal: assert the safe run-state (DTR/RTS levels per polarity) */
int  serial_safe_state(serial_t *s);

#endif /* SERIAL_H */
