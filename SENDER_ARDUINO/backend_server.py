#!/usr/bin/env python3
"""
ActuLock Backend Server

Bridges the HTML/JS frontend to the real policy engine and, if present,
the Input Arduino. This file contains NO policy rules of its own --
every decision comes from policy_engine.evaluate(), which reads
policy.json. That's the whole point: one copy of the rules, reused
everywhere.

Run:
    pip install flask pyserial
    python backend_server.py

Then open http://localhost:5000/homepage.html
"""

import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))
import policy_engine
from event_registry import EVENTS, get_event

try:
    import serial
except ImportError:
    serial = None  # backend still runs -- hardware calls just report "not available"

BASE_DIR = Path(__file__).parent
POLICY_PATH = BASE_DIR / "policy.json"

# The four HTML files can live right next to this script, or in a
# sibling "web/" folder (the layout tools/check_contract.py assumes,
# with this script living in "policy/" alongside policy.json and a
# sibling "web/" folder holding the HTML). Rather than hardcode one
# guess, try the plausible spots in order and use whichever one
# actually has homepage.html in it.
_WEB_DIR_CANDIDATES = [
    BASE_DIR,
    BASE_DIR / "web",
    BASE_DIR.parent / "web",
]


def _resolve_web_dir():
    for candidate in _WEB_DIR_CANDIDATES:
        if (candidate / "homepage.html").is_file():
            return candidate
    return BASE_DIR  # nothing found -- fall back to a path that at least exists


WEB_DIR = _resolve_web_dir()

app = Flask(__name__)

# One serial connection, opened lazily and reused across requests rather
# than reopened per click (reopening resets most Arduino boards).
_ser = None
_ser_error = None
_last_serial_attempt = 0.0
SERIAL_RETRY_COOLDOWN = 5.0  # seconds


def get_serial(policy):
    """Returns an open, handshake-verified serial connection, or None.
    Never raises -- a missing/disconnected Arduino should degrade the
    demo to 'policy decision without hardware', not crash the server."""
    global _ser, _ser_error, _last_serial_attempt

    if serial is None:
        _ser_error = "pyserial not installed"
        return None

    if _ser is not None and _ser.is_open:
        return _ser

    # Fail fast if we just tried and failed. Without this, every
    # /api/check request re-runs the full ~2s open+handshake whenever
    # no Arduino is attached, and pages that fire several checks per
    # verification pass (dam, robot arm) turn into a many-second stall.
    now = time.time()
    if _ser_error is not None and (now - _last_serial_attempt) < SERIAL_RETRY_COOLDOWN:
        return None
    _last_serial_attempt = now

    try:
        _ser = serial.Serial(policy["serial_port"], policy["baud_rate"], timeout=1)
        time.sleep(2)  # let the board reset after the port opens
        if not policy_engine.check_connection(_ser):
            _ser_error = "Port opened but Arduino did not respond to PING (wrong sketch? Serial Monitor open elsewhere?)"
            _ser.close()
            _ser = None
            return None
        _ser_error = None
        return _ser
    except Exception as e:
        _ser_error = str(e)
        _ser = None
        return None


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "homepage.html")


@app.route("/<path:filename>")
def static_files(filename):
    # Serves homepage.html, damcontrol1.html, ivbloodpump1.html,
    # robotarm1.html and any assets alongside them.
    return send_from_directory(WEB_DIR, filename)


@app.route("/api/events")
def api_events():
    """Lets the frontend fetch event names/ids instead of hardcoding them twice."""
    return jsonify({str(eid): info for eid, info in EVENTS.items()})


@app.route("/api/check", methods=["POST"])
def api_check():
    """
    Body:  { "event_id": 3, "action": "OPEN_GATE", "value": 85,
              "agent": "web-ui", "reasoning": "operator request" }
    Reply: { "event": {...}, "approved": bool, "reason": str,
              "protocol_line": str,
              "hardware": { "attempted": bool, "connected": bool,
                             "response": str|null, "error": str|null } }
    """
    body = request.get_json(force=True, silent=True) or {}

    try:
        event_id = int(body.get("event_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "event_id must be an integer"}), 400

    if event_id not in EVENTS:
        return jsonify({"error": f"unknown event_id {event_id}"}), 400

    intent = {
        "agent": body.get("agent", "web-ui"),
        "intent": {"action": body.get("action"), "value": body.get("value")},
        "reasoning": body.get("reasoning", ""),
    }

    policy = policy_engine.load_json(POLICY_PATH)
    approved, reason = policy_engine.evaluate(event_id, intent, policy)
    line = policy_engine.build_protocol_line(event_id, intent, approved)
    policy_engine.log_line(
        f"{'APPROVE' if approved else 'DENY'} | event={get_event(event_id)['name']} "
        f"| intent={intent['intent']} | reason={reason} | via=backend_server"
    )

    hardware = {"attempted": False, "connected": False, "response": None, "error": None}
    use_serial = body.get("use_serial", True)

    if not approved:
        # Denied commands must never reach the wire at all -- not even
        # with DECISION:DENY in the line. The Sender Arduino cannot be
        # trusted as the only backstop (we don't control that firmware
        # here), so this is the one place that's guaranteed to run:
        # if it's not approved, nothing is written to the serial port,
        # which means it physically cannot reach the Receiver.
        hardware["error"] = "blocked by policy -- not sent to hardware"
    elif use_serial:
        hardware["attempted"] = True
        ser = get_serial(policy)
        if ser is None:
            hardware["error"] = _ser_error
        else:
            try:
                response = policy_engine.send_to_hardware(ser, line)
                hardware["connected"] = True
                hardware["response"] = response or None
            except Exception as e:
                hardware["error"] = str(e)

    return jsonify({
        "event": get_event(event_id),
        "approved": approved,
        "reason": reason,
        "protocol_line": line.strip(),
        "hardware": hardware,
    })


@app.route("/api/check_batch", methods=["POST"])
def api_check_batch():
    """
    All-or-nothing version of /api/check for one logical command made
    of several parameters (e.g. dam gate + turbine + valves, or all 4
    robot-arm axes). If ANY action in the batch is denied, NOTHING in
    the batch is sent to hardware -- not even the ones that were
    individually fine. This is what makes "turbine over-limit, gate
    fine" result in the gate never moving either.

    Body:  { "event_id": 3, "agent": "web-ui",
              "actions": [ {"action": "OPEN_GATE", "value": 85, "reasoning": "..."},
                            {"action": "SET_TURBINE_RPM", "value": 1200, "reasoning": "..."} ],
              "use_serial": true }
    Reply: { "event": {...}, "all_approved": bool,
              "results":  [ {"action":.., "value":.., "approved":.., "reason":..}, ... ],
              "hardware": [ {"action":.., "attempted":.., "connected":.., "response":.., "error":..}, ... ] }
    """
    body = request.get_json(force=True, silent=True) or {}

    try:
        event_id = int(body.get("event_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "event_id must be an integer"}), 400

    if event_id not in EVENTS:
        return jsonify({"error": f"unknown event_id {event_id}"}), 400

    actions = body.get("actions")
    if not isinstance(actions, list) or not actions:
        return jsonify({"error": "actions must be a non-empty list"}), 400

    agent = body.get("agent", "web-ui")
    use_serial = body.get("use_serial", True)

    intents = [{
        "agent": agent,
        "intent": {"action": item.get("action"), "value": item.get("value")},
        "reasoning": item.get("reasoning", ""),
    } for item in actions]

    policy = policy_engine.load_json(POLICY_PATH)

    # Pass 1: dry-run every action (commit=False) to find out whether
    # the WHOLE batch is clean, without burning any rate-limit slot or
    # touching hardware yet.
    results = []
    all_approved = True
    for intent in intents:
        approved, reason = policy_engine.evaluate(event_id, intent, policy, commit=False)
        results.append({
            "action": intent["intent"]["action"],
            "value": intent["intent"]["value"],
            "approved": approved,
            "reason": reason,
        })
        if not approved:
            all_approved = False

    hardware_results = [{"action": r["action"], "attempted": False,
                          "connected": False, "response": None, "error": None}
                         for r in results]

    if not all_approved:
        for hw in hardware_results:
            hw["error"] = "blocked by policy -- a sibling action in this batch was denied, so nothing was sent"
        for r in results:
            policy_engine.log_line(
                f"{'APPROVE' if r['approved'] else 'DENY'} | event={get_event(event_id)['name']} "
                f"| intent={{'action': r['action'], 'value': r['value']}} | reason={r['reason']} "
                f"| via=backend_server(batch, BLOCKED)"
            )
        return jsonify({
            "event": get_event(event_id), "all_approved": False,
            "results": results, "hardware": hardware_results,
        })

    # Pass 2: every action in the batch passed independently -- now
    # actually commit (rate-limit timestamps) and send each line to
    # hardware, one at a time, in order.
    for intent, r, hw in zip(intents, results, hardware_results):
        policy_engine.evaluate(event_id, intent, policy, commit=True)
        line = policy_engine.build_protocol_line(event_id, intent, True)
        policy_engine.log_line(
            f"APPROVE | event={get_event(event_id)['name']} | intent={intent['intent']} "
            f"| reason={r['reason']} | via=backend_server(batch)"
        )
        if use_serial:
            hw["attempted"] = True
            ser = get_serial(policy)
            if ser is None:
                hw["error"] = _ser_error
            else:
                try:
                    response = policy_engine.send_to_hardware(ser, line)
                    hw["connected"] = True
                    hw["response"] = response or None
                except Exception as e:
                    hw["error"] = str(e)

    return jsonify({
        "event": get_event(event_id), "all_approved": True,
        "results": results, "hardware": hardware_results,
    })


if __name__ == "__main__":
    if not POLICY_PATH.exists():
        print(f"FATAL: {POLICY_PATH} not found.")
        sys.exit(1)

    if not (WEB_DIR / "homepage.html").is_file():
        print("WARNING: could not find homepage.html in any of:")
        for candidate in _WEB_DIR_CANDIDATES:
            print(f"    {candidate}")
        print("HTML routes will 404 until the four HTML files are placed in one "
              "of those folders (or edit _WEB_DIR_CANDIDATES above).")
    else:
        print(f"Serving HTML from: {WEB_DIR}")

    if serial is None:
        print("NOTE: pyserial not installed -- running with policy decisions only, "
              "no hardware. `pip install pyserial` to enable the Arduino link.")

    # debug=True runs Werkzeug's interactive debugger, which can execute
    # arbitrary code from the browser on an unhandled exception. That's a
    # real hole when combined with host="0.0.0.0" (reachable by anything
    # on the LAN), so it's off unless explicitly requested.
    debug_mode = os.environ.get("ACTULOCK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
