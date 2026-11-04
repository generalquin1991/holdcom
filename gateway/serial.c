/*
 * serial.c - STUB (skeleton, no core logic yet)
 *
 * Intended implementation notes (reference: picocom term.c / lowerrts.md):
 *   - serial_open: open(port, O_RDWR|O_NOCTTY|O_NONBLOCK); ioctl(TIOCEXCL) for
 *     exclusive ownership (blocks pyserial / anything else from opening);
 *     tcgetattr -> save orig; set raw, CLOCAL=1, HUPCL=0; commit; then
 *     serial_safe_state() (assert SAFE DTR/RTS immediately, before/after commit,
 *     because term commit may touch DTR/RTS - see picocom.c:2099).
 *   - serial_write/serial_read: straightforward read/write with timeout.
 *   - serial_get_mctl: ioctl(TIOCMGET) -> map TIOCM_* to dtr/rts/cts/dsr.
 *   - serial_safe_state: ioctl(TIOCMBIS/TIOCMBIC, &pins) for DTR/RTS per polarity.
 *
 * Deliberate modem-write commands (reset/boot/set_dtr/set_rts) and flash/yield
 * are intentionally NOT part of this skeleton (out of scope).
 *
 * None of the above is implemented yet - this is the structural skeleton.
 */
#include "serial.h"
#include <errno.h>
#include <stdio.h>
#include <sys/types.h>

int serial_open(serial_t *s, const char *port, speed_t baud)
{
    (void)s; (void)port; (void)baud;
    fprintf(stderr, "serial_open: NOT IMPLEMENTED (skeleton)\n");
    errno = ENOSYS;
    return -1;
}

void serial_close(serial_t *s)
{
    (void)s;
    fprintf(stderr, "serial_close: NOT IMPLEMENTED (skeleton)\n");
}

int serial_set_attr(serial_t *s, int databits, int stopbits, int parity, bool flow)
{
    (void)s; (void)databits; (void)stopbits; (void)parity; (void)flow;
    fprintf(stderr, "serial_set_attr: NOT IMPLEMENTED (skeleton)\n");
    return -1;
}

int serial_get_mctl(serial_t *s, int *dtr, int *rts, int *cts, int *dsr)
{
    (void)s; (void)dtr; (void)rts; (void)cts; (void)dsr;
    return -1;
}

ssize_t serial_write(serial_t *s, const void *buf, size_t n)
{
    (void)s; (void)buf; (void)n;
    return -1;
}

ssize_t serial_read(serial_t *s, void *buf, size_t n, int timeout_ms)
{
    (void)s; (void)buf; (void)n; (void)timeout_ms;
    return -1;
}

int serial_safe_state(serial_t *s)
{
    (void)s;
    fprintf(stderr, "serial_safe_state: NOT IMPLEMENTED (skeleton)\n");
    return -1;
}
