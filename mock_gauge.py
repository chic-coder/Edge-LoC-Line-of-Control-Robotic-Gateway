import time
import serial

SERIAL_PORT = "/dev/pts/0"
BAUD_RATE = 115200

def run_mock_gauge():
    print(f"[Mock Gauge] Opening serial port {SERIAL_PORT} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    except Exception as e:
        print(f"[Mock Gauge Error] Failed to open port: {e}")
        return

    # Sample test payloads varying from OK to Rework/Scrap conditions
    test_records = [
        "001 2608101430_00025 +010.0130 +010.0130 OK\r\n",
        "001 2608101430_00026 +010.0220 +010.0190 REWORK\r\n",  # Oversized -> Rework
        "001 2608101430_00027 +009.9800 +009.9850 REJECT\r\n"   # Undersized -> Scrap
    ]

    while True:
        for record in test_records:
            ser.write(record.encode("ascii"))
            print(f"[Mock Gauge Sent] {record.strip()}")
            time.sleep(3)

if __name__ == "__main__":
    run_mock_gauge()
