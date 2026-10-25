import socket

HOST = "127.0.0.1" # local IP address for testing
PORT = 8193 #industry-standard default TCP port used by FANUC controllers for FOCAS Ethernet communications.

def run_mock_fanuc():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f"[Mock FANUC] Listening for Ethernet commands on {HOST}:{PORT}...")

    while True:
        conn, addr = server.accept()
        print(f"[Mock FANUC] Connected by gateway client: {addr}")
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                command = data.decode("utf-8").strip()
                print(f"[Mock FANUC Received] {command}")
                
                # Send back acknowledgement (ACK)
                ack_response = "ACK\r\n"
                conn.sendall(ack_response.encode("utf-8"))
        except ConnectionResetError:
            print("[Mock FANUC] Connection dropped by client.")
        finally:
            conn.close()

if __name__ == "__main__":
    run_mock_fanuc()
