# uart-gateway Makefile (skeleton)
# Builds the stub daemon so the structure is reviewable & compiles cleanly.
# Core logic is NOT implemented yet (see src/*.c stubs).

CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -std=c11
TARGET   = uart-gateway
SRCS     = main.c serial.c server.c
OBJS     = $(SRCS:.c=.o)

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)

%.o: %.c serial.h server.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)
