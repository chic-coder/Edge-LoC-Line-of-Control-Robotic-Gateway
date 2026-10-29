# gateway/decision.py
"""Encapsulates telemetry processing business constraints and categorization matrix logic."""
from .config import (NOMINAL, LSL, REWORK_MAX, USL, PROBE_TOL, SEVERITY,
                     OFFSET_DEADBAND, MACRO_VAR, PMC_ADDR, SORT_BIT)

def probe_verdict(ch: float) -> str:
    dev = round(ch - NOMINAL, 4)
    if dev < LSL or dev > REWORK_MAX:
        return "REJECT"
    if dev > USL:
        return "REWORK"
    return "OK"
   
def classify_part(ch1: float, ch2: float) -> str:
    """Calculates classifications and guarantees dual-probe consensus fallback."""
    verdict = max(probe_verdict(ch1), probe_verdict(ch2), key=SEVERITY.get)
    if verdict == "OK" and abs(round(ch1 - ch2, 4)) > PROBE_TOL:   
        verdict = "REWORK"
    return verdict

def tool_offset(ch1: float, ch2: float, verdict: str):
    """Mean deviation from nominal, or None when no correction should be sent.

    None for REJECT parts (an outlier must not move the tool) and inside the
    deadband (that would be chasing probe noise).
    """
    if verdict == "REJECT":
        return None
    mean_dev = round((ch1 + ch2) / 2 - NOMINAL, 4)
    return mean_dev if abs(mean_dev) >= OFFSET_DEADBAND else None

def build_commands(verdict: str, ch1: float, ch2: float) -> list:
    """Sorting command always; macro offset command only when warranted."""
    commands = [f"pmc_wrrange({PMC_ADDR}, {SORT_BIT[verdict]})"]
    offset = tool_offset(ch1, ch2, verdict)
    if offset is not None:
        commands.append(f"cnc_wrmacro(#{MACRO_VAR}, {offset:+.4f})")
    return commands