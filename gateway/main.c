/*
 * main.c - uart-gateway entry point (skeleton, arg parsing only)
 *
 * Usage (frozen config, see docs/INTERFACE.md §5):
 *   uart-gateway -p <port> -b <baud> [-s <unix-socket>]
 *                [-P <dtr_polarity>] [-R <rts_polarity>]
 *                [--send-crlf] [--daemon]
 */
#include "serial.h"
#include "server.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void usage(const char *p)
{
    fprintf(stderr,
        "uart-gateway (SKELETON - logic not implemented)\n"
        "usage: %s -p <port> -b <baud> [-s <unix-socket>]\n"
        "          [-P <dtr_polarity>] [-R <rts_polarity>]\n"
        "          [--send-crlf] [--daemon]\n", p);
}

int main(int argc, char **argv)
{
    const char *port = NULL;
    const char *sock_path = "/tmp/uart-gateway.sock";
    int  baud     = 115200;
    int  dtr_pol  = 0;     /* 0 = low-active (safe = high), 1 = high-active */
    int  rts_pol  = 0;
    int  send_crlf = 0;
    int  daemonize = 0;
    int  opt;

    while ((opt = getopt(argc, argv, "p:b:s:P:R:h")) != -1) {
        switch (opt) {
        case 'p': port = optarg; break;
        case 'b': baud = atoi(optarg); break;
        case 's': sock_path = optarg; break;
        case 'P': dtr_pol = atoi(optarg); break;
        case 'R': rts_pol = atoi(optarg); break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }
    /* --send-crlf / --daemon handled via getopt_long in real impl */
    (void)send_crlf; (void)daemonize;

    if (!port) { usage(argv[0]); return 1; }

    printf("[skeleton] port=%s baud=%d sock=%s dtr_pol=%d rts_pol=%d\n",
           port, baud, sock_path ? sock_path : "(none)", dtr_pol, rts_pol);

    serial_t ser = {0};
    server_cfg_t cfg = { .ser = &ser, .sock_path = (char*)sock_path };

    /* Real flow: serial_open -> serial_set_attr -> serial_safe_state -> server_start */
    return server_start(&cfg);
}
