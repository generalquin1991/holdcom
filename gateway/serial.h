/*
 * serial.h - serial port ownership & modem-line control (clean-room)
 *
 * Reference only: picocom's term.c / lowerrts.md (GPL-2.0, NOT copied).
 * This file implements NO logic yet; it is the interface skeleton.
 */
#ifndef SERIAL_H
#define SERIAL_H

#include <stdbool.h>
#include <termios.h>

typedef struct {
    int      fd;          /* serial fd, -1 when closed */
    char    *port;        /* e.g. /dev/cu.usbserial-XXXX */
    speed_t  baud;
    int      databits;    /* 5..8 */
    int      stopbits;    /* 1..2 */
    int      parity;      /* 0=none,1=odd,2=even */
    bool     flow;        /* hardware RTS/CTS flow control */
    bool     local;       /* CLOCAL (ignore modem status / DCD) */
    bool     hupcl;       /* HUPCL: drop DTR on close (we keep this false) */
    struct termios orig;  /* saved original termios for restore */
} serial_t;

/* lifecycle */
int  serial_open (serial_t *s, const char *port, speed_t baud);
void serial_close(serial_t *s);

/* attribute configuration (applied to "next" termios, then committed) */
int  serial_set_attr(serial_t *s, int databits, int stopbits, int parity, bool flow);

/* modem control lines (ioctl TIOCMBIS / TIOCMBIC) */
int  serial_raise_dtr(serial_t *s);
int  serial_lower_dtr(serial_t *s);
int  serial_raise_rts(serial_t *s);
int  serial_lower_rts(serial_t *s);
int  serial_get_mctl(serial_t *s, int *dtr, int *rts, int *cts, int *dsr);

/* high-level ESP32 sequences (explicit, AI-controlled only) */
int  serial_reset_pulse(serial_t *s);  /* toggle EN: one low pulse on RTS */
int  serial_enter_boot (serial_t *s);  /* esptool DTR/RTS dance -> download mode */
int  serial_safe_state (serial_t *s);  /* DTR=1, RTS=1 -> EN high, IO0 high (run) */

#endif /* SERIAL_H */
