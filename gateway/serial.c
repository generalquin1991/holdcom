/*
 * serial.c - STUB (skeleton, no core logic yet)
 *
 * Intended implementation notes (reference: picocom term.c / lowerrts.md):
 *   - serial_open:  open(port, O_RDWR|O_NOCTTY); ioctl(TIOCEXCL) for exclusive
 *                   ownership (blocks pyserial / anything else from opening);
 *                   tcgetattr -> save orig; set raw, CLOCAL=1, HUPCL=0;
 *                   commit; then serial_safe_state() (DTR=1,RTS=1).
 *   - modem lines:  ioctl(fd, TIOCMBIS/TIOCMBIC, &pins) with TIOCM_DTR/RTS.
 *   - serial_safe_state must run IMMEDIATELY after open AND after term commit,
 *                   because term_apply() may reset DTR/RTS (see picocom.c:2099).
 *   - serial_enter_boot: replicate esptool sequence (DTR/RTS toggles).
 *
 * None of the above is implemented yet - this is the structural skeleton.
 */
#include "serial.h"
#include <errno.h>
#include <stdio.h>

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

int serial_raise_dtr(serial_t *s) { (void)s; fprintf(stderr,"raise_dtr: NI\n"); return -1; }
int serial_lower_dtr(serial_t *s) { (void)s; fprintf(stderr,"lower_dtr: NI\n"); return -1; }
int serial_raise_rts(serial_t *s) { (void)s; fprintf(stderr,"raise_rts: NI\n"); return -1; }
int serial_lower_rts(serial_t *s) { (void)s; fprintf(stderr,"lower_rts: NI\n"); return -1; }

int serial_get_mctl(serial_t *s, int *dtr, int *rts, int *cts, int *dsr)
{
    (void)s; (void)dtr; (void)rts; (void)cts; (void)dsr;
    return -1;
}

int serial_reset_pulse(serial_t *s) { (void)s; fprintf(stderr,"reset_pulse: NI\n"); return -1; }
int serial_enter_boot (serial_t *s) { (void)s; fprintf(stderr,"enter_boot: NI\n"); return -1; }
int serial_safe_state(serial_t *s)  { (void)s; fprintf(stderr,"safe_state: NI\n"); return -1; }
