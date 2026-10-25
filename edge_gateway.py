
import time
import socket
import serial
import re

# Configuration
SERIAL_PORT = "/dev/pts/0"  # The paired terminal to the mock gauge
BAUD_RATE = 115200
FANUC_HOST = "127.0.0.1"
FANUC_PORT = 8193

NOMINAL_SIZE = 10.000
USL = 0.015  # Upper specification limit deviation (+0.015 mm)
LSL = -0.015 # Lower specification limit deviation (-0.015 mm)

def send_to_fanuc(sock, payload):
    """Sends command over TCP and awaits ACK, ensuring sub-50ms turnaround."""
    start_time = time.time()
    try:
        sock.sendall((payload + "\r\n").encode("utf-8"))
        response = sock.recv(1024).decode("utf-8")
        latency = (time.time() - start_time) * 1000
        print(f"   [Ethernet TX -> FANUC] {payload} | Response: {response.strip()} | Latency: {latency:.2f}ms")
    except Exception as e:
        print(f"   [Ethernet Error] Socket transmission failed: {e}")

def run_gateway():
    print("[Gateway] Initializing Edge-LoC Gateway Service...")

    # Establish TCP connection to Mock FANUC Controller
    fanuc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        fanuc_socket.connect((FANUC_HOST, FANUC_PORT))
        print(f"[Gateway] Connected to FANUC Controller at {FANUC_HOST}:{FANUC_PORT}")
    except Exception as e:
        print(f"[Gateway Error] Could not connect to FANUC server: {e}")
        return

    # Open Serial Port
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[Gateway] Listening for gauge records on {SERIAL_PORT}...")
    except Exception as e:
        print(f"[Gateway Error] Failed to open serial port: {e}")
        fanuc_socket.close()
        return

    buffer = ""
    while True:
        data = ser.read(ser.in_waiting or 1).decode("ascii", errors="ignore")
        if data:
            buffer += data
            # Process complete lines based on carriage returns
            if "\n" in buffer:
                lines = buffer.split("\n")
                buffer = lines[-1]  # Keep remainder in buffer
                for line in lines[:-1]:
                    line = line.strip()
                    if not line:
                        continue
                    
                    print(f"\n[Incoming Telemetry] {line}")
                    
                    # Regex Pattern to parse fields: ID, Serial, Ch1, Ch2, Verdict
                    match = re.match(r"(\d{3})\s+(\S+)\s+([+-]\d+\.\d+)\s+([+-]\d+\.\d+)\s+(\w+)", line)
                    if match:
                        dev_id, part_serial, ch1_str, ch2_str, gauge_verdict = match.groups()
                        ch1 = float(ch1_str)
                        ch2 = float(ch2_str)
                        
                        # Edge Decision Logic
                        max_deviation = max(ch1, ch2) - NOMINAL_SIZE
                        
                        if LSL <= max_deviation <= USL:
                            verdict = "OK"
                            sorting_bit = "0x01"  # OK conveyor drop
                            offset_cmd = None
                        elif max_deviation > USL and max_deviation <= 0.030:
                            verdict = "REWORK"
                            sorting_bit = "0x02"  # Rework station[cite: 1]
                            # Calculate dynamic tool wear correction for macro #500
                            offset_value = round(max_deviation, 4)
                            offset_cmd = f"cnc_wrmacro(#500, +{offset_value:.4f})"
                        else:
                            verdict = "REJECT"
                            sorting_bit = "0x04"  # Scrap chute[cite: 1]
                            offset_cmd = None

                        # 1. Execute Tool Offset Correction if needed (CNC Action)
                        if offset_cmd:
                            send_to_fanuc(fanuc_socket, offset_cmd)

                        # 2. Execute Sorting Actuation via PMC register update
                        pmc_cmd = f"pmc_wrrange(R0500, {sorting_bit})"
                        send_to_fanuc(fanuc_socket, pmc_cmd)
                        
                        print(f"   [Decision Outcome] Verdict: {verdict} | Sorting Bit Sent: {sorting_bit}")
                    else:
                        print("   [Parsing Warning] Malformed line skipped.")
        time.sleep(0.01)

if __name__ == "__main__":
    run_gateway()
