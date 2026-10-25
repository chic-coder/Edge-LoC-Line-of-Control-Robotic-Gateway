import argparse
import random
import re
import socket
import threading
import time
from datetime import datetime

HOST = "127.0.0.1" #local ip address for testing
PORT= 8193 ##industry-standard default TCP port used by FANUC controllers for FOCAS Ethernet communications.

MACRO = re.compile(r"cnc_wrmacro\(#(\d+),\s*([+-]?\d+(?:\.\d+)?)\)")
PMC = re.compile(r"pmc_wrrange\((R\d{4}),\s*(0x[0-9A-Fa-f]{1,2}|\d{1,3})\)")

macro_vars = {}      # {500: "+0.013"}
pmc_bytes = {}       # {"R0500": 1}
lock = threading.Lock()
cmd_count = 0

def log(msg):
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  {msg}", flush=True)

def apply(command):
    """Parse and apply one command. Returns None on success or an error string."""
    m = MACRO.fullmatch(command)
    if m:
        with lock:
            macro_vars[int(m.group(1))] = m.group(2)
        log(f"cnc_wrmacro  #{m.group(1)} = {m.group(2)}")
        return None
    m = PMC.fullmatch(command)
    if m:
        value = int(m.group(2), 0)
        if not 0 <= value <= 255:
            return "BYTE_RANGE"
        with lock:
            pmc_bytes[m.group(1)] = value
        log(f"pmc_wrrange  {m.group(1)} = 0x{value:02X}")
        return None
    return "BAD_CMD"

def handle_client(conn, addr, args, rng):
    global cmd_count
    log(f"gateway connected from {addr[0]}:{addr[1]}")
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    f = conn.makefile("rb")   # buffered readline() = proper line framing over TCP
    try:
        conn.sendall(b"READY\r\n")
        while True:
            raw = f.readline(4096)
            if not raw:
                break
            command = raw.decode("utf-8", errors="replace").strip()
            if not command:
                continue
            with lock:
                cmd_count += 1
                n = cmd_count
            if args.ack_delay_ms:
                time.sleep(args.ack_delay_ms / 1000)
            if rng.random() < args.nak_rate:
                log(f"FAULT: NAK injected for {command}")
                conn.sendall(b"NAK BUSY\r\n")
                continue
            error = apply(command)
            if error:
                log(f"rejected {command!r}: {error}")
                conn.sendall(f"NAK {error}\r\n".encode())
                continue
            if args.drop_every and n % args.drop_every == 0:
                log("FAULT: command applied, dropping connection before ACK")
                break
            conn.sendall(b"ACK\r\n")
    except OSError:
        pass
    finally:
        f.close()
        conn.close()
        log("gateway disconnected")

def main():
    p = argparse.ArgumentParser(description="Mock FANUC controller")
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--ack-delay-ms", type=float, default=0)
    p.add_argument("--nak-rate", type=float, default=0)
    p.add_argument("--drop-every", type=int, default=0)
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()
    if args.drop_every and args.drop_every < 3:
        p.error("--drop-every must be >= 3 (a cycle sends 2 commands; 2 would drop every retry)")

    rng = random.Random(args.seed)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(5)
    log(f"Mock FANUC listening on {args.host}:{args.port}")
    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr, args, rng), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        print(f"\nFinal state: macro={macro_vars}  pmc="
              f"{ {k: hex(v) for k, v in pmc_bytes.items()} }  commands={cmd_count}")

if __name__ == "__main__":
    main()
