# gateway/parser.py
"""Handles translation of raw wire-bytes into validated data objects."""
import re

RECORD_REGEX = re.compile( r"(\d{3}) (\d{10}_\d{5}) ([+-]\d{3}\.\d{4}) ([+-]\d{3}\.\d{4}) (OK|REWORK|REJECT)\Z")

def parse_record(raw: bytes) -> dict:
    """Decodes string fields and extracts float values. Raises ValueError on corruption."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("non-ASCII bytes detected")
    
    m = RECORD_REGEX.search(text)
    if not m:
        raise ValueError("bad format or field count mismatch")

    device, part, c1, c2, gauge = m.groups()
    return {
        "device": device, "part": part,
        "ch1": float(c1), "ch2": float(c2), "gauge": gauge
    }
