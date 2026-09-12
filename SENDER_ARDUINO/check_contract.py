#!/usr/bin/env python3
"""
ActuLock -- Contract Sync Checker

Confirms two things stay in sync between the Python side and the
Arduino side:
  1. Event names/order: policy/event_registry.py  <->  firmware/arduino_output/main.ino
  2. Per-action bounds:  policy/policy.json        <->  firmware/arduino_input/main.ino's BOUNDS[] table

Run this before every merge to main.

Usage:
    python tools/check_contract.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REGISTRY_PATH = ROOT / "policy" / "event_registry.py"
POLICY_PATH = ROOT / "policy" / "policy.json"
OUTPUT_FW_PATH = ROOT / "firmware" / "arduino_output" / "main.ino"
INPUT_FW_PATH = ROOT / "firmware" / "arduino_input" / "main.ino"

RED = "\033[91m"
GREEN = "\033[92m"
BOLD = "\033[1m"
RESET = "\033[0m"

ok = True


def load_python_events():
    sys.path.insert(0, str(REGISTRY_PATH.parent))
    import event_registry
    return [event_registry.EVENTS[i]["name"] for i in sorted(event_registry.EVENTS)]


def load_arduino_events():
    text = OUTPUT_FW_PATH.read_text()
    match = re.search(r"EVENT_NAMES\[EVENT_COUNT\]\s*=\s*\{(.*?)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find EVENT_NAMES array in arduino_output/main.ino")
    return re.findall(r'"([^"]+)"', match.group(1))


def load_policy_bounds():
    """Returns a sorted set of (event_id, action, min, max) tuples."""
    policy = json.loads(POLICY_PATH.read_text())
    bounds = set()
    for event_id_str, event_rules in policy["events"].items():
        for action, rule in event_rules.get("actions", {}).items():
            bounds.add((int(event_id_str), action, rule["min_value"], rule["max_value"]))
    return bounds


def load_arduino_bounds():
    """Parses the BOUNDS[] struct array in arduino_input/main.ino."""
    text = INPUT_FW_PATH.read_text()
    match = re.search(r"BOUNDS\[BOUND_COUNT\]\s*=\s*\{(.*?)\};", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find BOUNDS array in arduino_input/main.ino")
    rows = re.findall(
        r'\{\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}',
        match.group(1)
    )
    return {(int(eid), action, int(mn), int(mx)) for eid, action, mn, mx in rows}


def report(label, python_set, arduino_set):
    global ok
    print(f"{BOLD}{label}{RESET}")
    only_py = python_set - arduino_set
    only_ino = arduino_set - python_set
    if not only_py and not only_ino:
        print(f"  {GREEN}OK{RESET} -- {len(python_set)} entries match.")
    else:
        ok = False
        for row in sorted(only_py):
            print(f"  {RED}in policy.json but not in Arduino:{RESET} {row}")
        for row in sorted(only_ino):
            print(f"  {RED}in Arduino but not in policy.json:{RESET} {row}")
    print()


def main():
    py_events = load_python_events()
    ino_events = load_arduino_events()
    print(f"{BOLD}Event names/order{RESET}")
    print(f"  python  : {py_events}")
    print(f"  arduino : {ino_events}")
    if py_events == ino_events:
        print(f"  {GREEN}OK{RESET}\n")
    else:
        print(f"  {RED}MISMATCH{RESET}\n")
        global ok
        ok = False

    report("Per-action bounds (event_id, action, min, max)",
           load_policy_bounds(), load_arduino_bounds())

    if ok:
        print(f"{GREEN}{BOLD}IN SYNC{RESET} -- safe to merge.")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}FIX BEFORE MERGING.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
