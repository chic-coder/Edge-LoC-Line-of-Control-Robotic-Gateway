# gateway/line_framer.py
"""Handles low-level data streaming fragmentation and framing over serial interfaces."""

class LineFramer:
    def __init__(self, max_line=128):
        self.buf = bytearray()
        self.max_line = max_line

    def feed(self, data: bytes):
        """Accumulates binary fragments and returns properly sliced ASCII packets."""
        self.buf += data
        lines = []
        while True:
            i = self.buf.find(b"\n")
            if i == -1:
                if len(self.buf) > self.max_line:
                    self.buf.clear()  # Purge buffers during garbage overflows
                break
            chunk = bytes(self.buf[:i]).rstrip(b"\r")
            del self.buf[:i + 1]
            if chunk:
                lines.append(chunk)
        return lines
