import argparse #for parsing the command-line arguments
import re #for parsing the command-line arguments
import socket #for TCP communication with the FANUC server
import time #for the datetime and sleep functions
import serial #serial is used for serial communication with the mock gauge 
# ----------------------------------------------------------------------------
# Configuration & Tolerances
# ----------------------------------------------------------------------------
NOMINAL = 10.000
USL = 0.015          # +0.015 mm -> above this is REWORK
LSL = -0.015         # -0.015 mm -> below this is REJECT (scrap)
REWORK_MAX = 0.030   # above this is REJECT
PROBE_TOL = 0.010    # max allowed |ch1 - ch2| before the part is sent to REWORK
MACRO_VAR = 500      # CNC macro variable for tool offset (#500)
PMC_ADDR = "R0500"   # PMC register for sorting bits

SORT_BIT = {"OK": "0x01", "REWORK": "0x02", "REJECT": "0x04"}
SEVERITY = {"OK": 0, "REWORK": 1, "REJECT": 2}

SOCK_TIMEOUT = 2.0                      # seconds, connect + every read
MAX_RETRIES = 5                         # attempts per cycle before it is dropped
BACKOFF_START, BACKOFF_MAX = 0.2, 3.0   # reconnect backoff, seconds

RECORD_REGEX = re.compile( r"(\d{3})\s+(\S+)\s+([+-]\d+\.\d+)\s+([+-]\d+\.\d+)\s+(OK|REWORK|REJECT)")

# ----------------------------------------------------------------------------
# Serial side: framing + parsing
# ----------------------------------------------------------------------------
class LineFramer:
    """Safely handles partial reads and split lines from the serial buffer."""
    def __init__(self, max_line=128):
        self.buf = bytearray()
        self.max_line = max_line

    def feed(self, data):
        self.buf += data
        lines = []
        while True:
            i = self.buf.find(b"\n")
            if i == -1:
                if len(self.buf) > self.max_line:
                    self.buf.clear()  # drop overflow junk
                break
            chunk = bytes(self.buf[:i]).rstrip(b"\r")
            del self.buf[:i + 1]
            if chunk:
                lines.append(chunk)
        return lines

def parse_record(raw):
    """Strictly parse one ASCII record; raise ValueError if malformed."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("non-ASCII bytes")

    m = RECORD_REGEX.fullmatch(text)
    if not m:
        raise ValueError("bad format or field count")

    device, part, c1, c2, gauge = m.groups()
    return {"device": device, "part": part,
            "ch1": float(c1), "ch2": float(c2), "gauge": gauge}


# ----------------------------------------------------------------------------
# Decision logic
# ----------------------------------------------------------------------------
def probe_verdict(ch):
    dev = ch - NOMINAL
    if dev < LSL or dev > REWORK_MAX:
        return "REJECT"
    if dev > USL:
        return "REWORK"
    return "OK"

def classify_part(ch1, ch2):
    """Worst probe wins; probes that disagree too much -> REWORK."""
    verdict = max(probe_verdict(ch1), probe_verdict(ch2), key=SEVERITY.get)
    if verdict == "OK" and abs(ch1 - ch2) > PROBE_TOL + 1e-9:
        verdict = "REWORK"
    return verdict

# ----------------------------------------------------------------------------
# Ethernet side: FANUC client with handshake, timeouts, reconnect
# ----------------------------------------------------------------------------
class FanucClient:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.sock = None
        self.rfile = None

    def connect(self):
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=SOCK_TIMEOUT)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(SOCK_TIMEOUT)
            rfile = sock.makefile("rb")
            banner = rfile.readline(64).strip()
            if banner != b"READY":
                raise ConnectionError(f"expected READY, got {banner!r}")
        except OSError:
            sock.close()
            raise
        self.sock, self.rfile = sock, rfile
        print(f"[Ethernet] Connected to FANUC at {self.host}:{self.port} (READY)")

    def close(self):
        for res in (self.rfile, self.sock):
            if res:
                try:
                    res.close()
                except OSError:
                    pass
        self.sock = self.rfile = None

    def send(self, commands):
        """Send all commands in one payload, wait for one ACK line per command.
        Returns round-trip latency in ms."""
        t0 = time.perf_counter_ns()
        payload = "".join(cmd + "\r\n" for cmd in commands)
        self.sock.sendall(payload.encode("ascii"))
        for cmd in commands:
            reply = self.rfile.readline(64)
            if not reply:
                raise ConnectionError("connection closed by controller")
            reply = reply.decode("ascii", "replace").strip()
            if not reply.startswith("ACK"):
                raise ConnectionError(f"{cmd} rejected: {reply}")
        return (time.perf_counter_ns() - t0) / 1e6


def deliver(client, commands):
    """Send one cycle's commands, reconnecting and resending on any failure.
    Safe to resend: both commands write absolute values (idempotent).
    Returns latency in ms, or None if the cycle had to be dropped."""
    backoff = BACKOFF_START
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if client.sock is None:
                client.connect()
            return client.send(commands)
        except OSError as e:  # includes timeouts and ConnectionError
            print(f"[Ethernet Error] attempt {attempt}/{MAX_RETRIES}: {e}")
            client.close()
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
    return None

# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Simplified Edge-LoC Gateway")
    parser.add_argument("--serial", default="/dev/pts/1", help="Serial port path")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1", help="FANUC server IP")
    parser.add_argument("--tcp-port", type=int, default=8193, help="FANUC server TCP port")
    args = parser.parse_args()

    print("[Gateway] Starting Simplified Edge-LoC Gateway Service...")
    try:
        ser = serial.Serial(args.serial, args.baud, timeout=0.1)
    except serial.SerialException as e:
        print(f"[Gateway Error] Failed to open serial port: {e}")
        return
    print(f"[Gateway] Listening for gauge telemetry on {args.serial}...")

    client = FanucClient(args.host, args.tcp_port)
    framer = LineFramer()

    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue

            for raw_line in framer.feed(data):
                try:
                    rec = parse_record(raw_line)
                except ValueError as e:
                    print(f"[Parsing Warning] Skipped malformed line: {e}")
                    continue

                verdict = classify_part(rec["ch1"], rec["ch2"])
                commands = [f"pmc_wrrange({PMC_ADDR}, {SORT_BIT[verdict]})"]

                # Tool-wear offset only for a genuine oversize part
                max_dev = max(rec["ch1"], rec["ch2"]) - NOMINAL
                if verdict == "REWORK" and max_dev > USL:
                    commands.append(f"cnc_wrmacro(#{MACRO_VAR}, {max_dev:+.4f})")

                latency = deliver(client, commands)

                print(f"\n[Telemetry] Dev {rec['device']} | Part {rec['part']} | "
                      f"Ch1 {rec['ch1']:+.4f} | Ch2 {rec['ch2']:+.4f}")
                if verdict != rec["gauge"]:
                    print(f"   [Mismatch] gauge said {rec['gauge']}, gateway computed {verdict}")
                if latency is None:
                    print(f"   [Dropped] {verdict}: controller unreachable after "
                          f"{MAX_RETRIES} attempts")
                else:
                    print(f"   [Decision] {verdict} | TX {' ; '.join(commands)} | "
                          f"ACK | {latency:.2f} ms")

    except KeyboardInterrupt:
        print("\n[Gateway] Shutting down...")
    except serial.SerialException as e:
        print(f"[Gateway Error] Serial link lost: {e}")
    finally:
        ser.close()
        client.close()


if __name__ == "__main__":
    main()
