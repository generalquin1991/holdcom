/*
 * main.c - uart-gateway entry point (skeleton, arg parsing only)
 *
 * Usage (planned):
 *   uart-gateway -p <port> -b <baud> [-s <unix-socket>]
 *                [-d <databits>] [-S <stopbits>] [-P <parity>]
 *                [--flow] [--dtr <0|1>] [--rts <0|1>]
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
        "          [-d <databits>] [-S <stopbits>] [-P <parity>] [--flow]\n"
        "          [--dtr <0|1>] [--rts <0|1>]\n", p);
}

int main(int argc, char **argv)
{
    const char *port = NULL;
    const char *sock_path = "/tmp/uart-gateway.sock";
    int  baud = 115200;
    int  databits = 8, stopbits = 1, parity = 0;
    int  dtr = 1, rts = 1;       /* ESP32 safe "run" state default */
    int  flow = 0;
    int  opt;

    while ((opt = getopt(argc, argv, "p:b:s:d:S:P:h")) != -1) {
        switch (opt) {
        case 'p': port = optarg; break;
        case 'b': baud = atoi(optarg); break;
        case 's': sock_path = optarg; break;
        case 'd': databits = atoi(optarg); break;
        case 'S': stopbits = atoi(optarg); break;
        case 'P': parity = atoi(optarg); break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }
    /* --flow / --dtr / --rts handled via getopt_long in real impl */
    (void)flow; (void)dtr; (void)rts;

    if (!port) { usage(argv[0]); return 1; }

    printf("[skeleton] port=%s baud=%d sock=%s db=%d sb=%d par=%d\n",
           port, baud, sock_path ? sock_path : "(none)",
           databits, stopbits, parity);

    serial_t ser = {0};
    server_cfg_t cfg = { .ser = &ser, .sock_path = (char*)sock_path };

    /* Real flow: serial_open -> serial_set_attr -> serial_safe_state -> server_start */
    return server_start(&cfg);
}
