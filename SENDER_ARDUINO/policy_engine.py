#!/usr/bin/env python3
"""
ActuLock Policy Engine (multi-event, multi-action)

Reads a simulated (or web-submitted) AI intent for a specific event,
checks it against that ACTION's rules within that event in policy.json,
and -- only if approved -- builds the protocol line and sends it to
the Sender (Input) Arduino.

Line sent to hardware (see docs/protocol.md):
    EVENT:<id>,DECISION:<APPROVE|DENY>,PARAM:<value>,ACTION:<name>

Note the ACTION field: the Sender Arduino uses it to look up the
PRECISE per-action bounds and re-check them independently. It is
stripped before the Sender relays anything to the Receiver -- the
Receiver's wire format is completely unchanged.

Usage:
    python policy_engine.py --event 1 agent/iv_pump/valid.json
    python policy_engine.py --event 3 agent/dam_gate/malicious.json --no-serial
"""

import argparse
import json
import sys
import time
import datetime
from pathlib import Path

from event_registry import get_event

try:
    import serial
except ImportError:
    # NOTE: this must NOT sys.exit(). backend_server.py does
    # `import policy_engine` unconditionally, and is designed to keep
    # running (policy decisions without hardware) even when pyserial
    # isn't installed. Exiting here used to kill the entire backend
    # process before Flask ever started, for every request, hardware
    # or not. The CLI entry point below (main()/run()) is the only
    # place that actually needs pyserial, and it now checks for and
    # reports this itself.
    serial = None

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

LOG_PATH = Path(__file__).parent / "actulock_audit.log"

# Rate limiting is per (event_id, action), not one global timestamp.
# damcontrol1.html and robotarm1.html each check several DIFFERENT
# actions (gate + turbine + valves; 4 joints) back-to-back as one
# logical operator command. Those are different actuators, so a single
# shared timestamp would falsely rate-limit the 2nd/3rd/4th action in
# that same batch just for arriving milliseconds later. Keying by
# actuator keeps the real protection this was meant to provide -- an
# agent still can't spam-repeat the SAME action faster than the
# configured interval -- without punishing a legitimate multi-actuator
# command.
_last_command_time = {}


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def log_line(text):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] {text}\n")


def evaluate(event_id, intent, policy, commit=True):
    """Returns (approved: bool, reason: str).

    commit=False runs every check (including the rate limit read) but
    does not write the rate-limit timestamp. Used for all-or-nothing
    batches: a multi-parameter command (e.g. dam gate + turbine) must
    be dry-run in full first, so that one action passing doesn't burn
    its rate-limit slot before we know a sibling action in the same
    batch is going to deny the whole thing."""
    global _last_command_time

    event_rules = policy["events"].get(str(event_id))
    if event_rules is None:
        return False, f"no policy defined for event_id {event_id}"

    action = intent.get("intent", {}).get("action")
    value = intent.get("intent", {}).get("value")

    action_rules = event_rules.get("actions", {}).get(action)
    if action_rules is None:
        return False, f"action '{action}' is not permitted for this event"

    if not isinstance(value, (int, float)):
        return False, "value must be numeric"

    if value < action_rules["min_value"] or value > action_rules["max_value"]:
        return False, (f"value {value} outside allowed range "
                        f"[{action_rules['min_value']}, {action_rules['max_value']}] "
                        f"for action '{action}'")

    key = (event_id, action)
    now = time.time()
    if now - _last_command_time.get(key, 0.0) < policy["min_seconds_between_commands"]:
        return False, "rate limit exceeded -- command sent too soon after the last one"

    if commit:
        _last_command_time[key] = now
    return True, "all checks passed"


def build_protocol_line(event_id, intent, approved):
    action = intent.get("intent", {}).get("action", "UNKNOWN")
    value = intent.get("intent", {}).get("value", 0)
    decision = "APPROVE" if approved else "DENY"
    return f"EVENT:{event_id},DECISION:{decision},PARAM:{value},ACTION:{action}\n"


def send_to_hardware(ser, line):
    ser.write(line.encode("utf-8"))
    time.sleep(0.05)
    response = ser.readline().decode("utf-8", errors="ignore").strip()
    return response


def check_connection(ser, timeout=2.0):
    """One-shot handshake: confirms the Sender's firmware is actually
    running and responding -- not just that the OS enumerated a USB
    device. See earlier notes: Device Manager showing the port is not
    the same thing as pyserial having a working, correctly-flashed
    board on the other end."""
    ser.reset_input_buffer()
    ser.write(b"PING\n")
    start = time.time()
    while time.time() - start < timeout:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "PONG":
            return True
        if line:
            continue
    return False


def run(event_id, intent_path, policy_path, use_serial=True):
    policy = load_json(policy_path)
    intent = load_json(intent_path)
    event = get_event(event_id)

    print(f"{CYAN}{BOLD}=== ActuLock Policy Engine ==={RESET}")
    print(f"Event      : {event['display_name']}  (id {event_id})")
    print(f"Agent      : {intent.get('agent', 'unknown')}")
    print(f"Intent     : {intent.get('intent')}")
    print(f"Reasoning  : {intent.get('reasoning', 'n/a')}")
    print("-" * 50)

    approved, reason = evaluate(event_id, intent, policy)

    if approved:
        print(f"{GREEN}{BOLD}>>> APPROVE{RESET}  ({reason})")
        log_line(f"APPROVE | event={event['name']} | intent={intent.get('intent')} | reason={reason}")
    else:
        print(f"{RED}{BOLD}>>> DENY{RESET}     ({reason})")
        log_line(f"DENY    | event={event['name']} | intent={intent.get('intent')} | reason={reason}")

    line = build_protocol_line(event_id, intent, approved)

    if not use_serial:
        print(f"{YELLOW}[--no-serial] Would send: {line.strip()}{RESET}")
        return

    if serial is None:
        print(f"{RED}pyserial not installed -- run: pip install pyserial{RESET}")
        print(f"{YELLOW}(or pass --no-serial to skip hardware entirely) Would send: {line.strip()}{RESET}")
        return

    try:
        ser = serial.Serial(policy["serial_port"], policy["baud_rate"], timeout=1)
        time.sleep(2)
    except serial.SerialException as e:
        print(f"{RED}Could not open serial port {policy['serial_port']}: {e}{RESET}")
        return

    if not check_connection(ser):
        print(f"{RED}{BOLD}Port opened, but the Arduino did not respond to a PING.{RESET}")
        ser.close()
        return
    print(f"{GREEN}Connection verified (PING/PONG).{RESET}")

    response = send_to_hardware(ser, line)
    print(f"Hardware   : {response if response else '(no response)'}")
    log_line(f"HARDWARE_RESPONSE | {response}")
    ser.close()


def main():
    parser = argparse.ArgumentParser(description="ActuLock policy engine")
    parser.add_argument("intent_file", help="Path to a JSON intent file")
    parser.add_argument("--event", type=int, required=True, help="Event id (1-3)")
    parser.add_argument("--policy", default=str(Path(__file__).parent / "policy.json"))
    parser.add_argument("--no-serial", action="store_true")
    args = parser.parse_args()
    run(args.event, args.intent_file, args.policy, use_serial=not args.no_serial)


if __name__ == "__main__":
    main()
