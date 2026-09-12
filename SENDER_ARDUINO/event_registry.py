"""
ActuLock Event Registry

Single source of truth (Python side) for event IDs -> names.
Must stay in sync with firmware/arduino_output/main.ino's EVENT_NAMES
array -- see docs/protocol.md and run tools/check_contract.py.

Only 3 events are live (Smart Door Lock was cut).
"""

EVENTS = {
    1: {"name": "IV_BLOOD_PUMP", "display_name": "IV Blood Pump", "unit": "mL/hr"},
    2: {"name": "ROBOTIC_ARM", "display_name": "Robotic Arm", "unit": "degrees"},
    3: {"name": "DAM_GATE", "display_name": "Dam Gate", "unit": "% open"},
}


def get_event(event_id):
    """Look up an event by id (accepts int or numeric string)."""
    return EVENTS[int(event_id)]
