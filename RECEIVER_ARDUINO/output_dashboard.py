#!/usr/bin/env python3
"""
ActuLock -- Output Dashboard (Laptop B / Receiver side)

Reads the Receiver Arduino's USB serial in a background thread and
serves a small live webpage showing exactly three things:
  1. Whether the receiver is actively getting data right now
  2. Which event was detected (IV Blood Pump / Robotic Arm / Dam Gate)
  3. What parameter was requested

Behavior added:
  - The moment the receiver flips from "RECEIVING DATA" to "NO SIGNAL",
    the "EVENT DETECTED" and "PARAMETER REQUESTED" boxes keep showing
    their last known values untouched -- no visible counting.
  - The server silently counts RESET_AFTER_SECONDS in the background.
    Once that grace window elapses, both boxes flip to "0" and hold
    there until a brand new EVENT_DETECTED line arrives from the
    Arduino, at which point the new event/param are shown immediately.

Usage:
    pip install flask pyserial
    python nodes/output_dashboard.py
    open http://localhost:5000
"""

import threading
import time
import serial
from flask import Flask, jsonify, render_template_string

PORT = "COM7"   # set to the Receiver Arduino's port on this laptop
BAUD = 9600
STALE_AFTER_SECONDS = 3   # no new line in this long -> shown as "NO SIGNAL"
RESET_AFTER_SECONDS = 3   # once NO SIGNAL, wait this long (silently) then blank event/param to "0"

app = Flask(__name__)

state_lock = threading.Lock()
state = {"event": "--", "param": "--", "decision": "--", "last_seen": 0.0}


def serial_reader():
    while True:
        try:
            ser = serial.Serial(PORT, BAUD, timeout=1)
        except serial.SerialException:
            print(f"Could not open {PORT}, retrying in 2s...")
            time.sleep(2)
            continue

        print(f"Listening on {PORT}...")
        while True:
            try:
                raw = ser.readline().decode("utf-8", errors="ignore").strip()
            except serial.SerialException:
                break  # device unplugged -- reopen the port and retry

            if not raw or not raw.startswith("EVENT_DETECTED:"):
                continue

            body = raw.replace("EVENT_DETECTED:", "EVENT:", 1)
            parts = {}
            for chunk in body.split("|"):
                if ":" in chunk:
                    k, _, v = chunk.partition(":")
                    parts[k] = v

            with state_lock:
                state["event"] = parts.get("EVENT", "--")
                state["decision"] = parts.get("DECISION", "--")
                state["param"] = parts.get("PARAM", "--")
                state["last_seen"] = time.time()


@app.route("/status")
def status():
    with state_lock:
        now = time.time()
        never_received = state["last_seen"] == 0.0
        elapsed = (now - state["last_seen"]) if not never_received else float("inf")
        receiving = elapsed < STALE_AFTER_SECONDS

        if never_received or receiving:
            # Nothing has come in yet, or data is actively flowing -- show it as-is.
            event_display = state["event"]
            param_display = state["param"]

        else:
            # Signal is lost. Keep showing the last known event/param untouched
            # (no visible countdown) for RESET_AFTER_SECONDS, counted silently
            # from the moment "NO SIGNAL" started. Only after that grace window
            # do both fields flip to "0" -- and they hold at "0" until a fresh
            # EVENT_DETECTED line comes in and updates state["event"]/["param"].
            time_since_stale = elapsed - STALE_AFTER_SECONDS

            if time_since_stale < RESET_AFTER_SECONDS:
                event_display = state["event"]
                param_display = state["param"]
            else:
                event_display = "0"
                param_display = "0"

        return jsonify({
            "receiving": receiving,
            "event": event_display,
            "param": param_display,
            "decision": state["decision"],
        })


PAGE = """
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>ACTULOCK OUTPUT SENTINEL</title>

  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
    rel="stylesheet">

  <style>

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    html,
    body {
      width: 100%;
      min-height: 100%;
    }

    body {
      min-height: 100vh;

      background:
        radial-gradient(
          circle at 50% 0%,
          #17202b 0%,
          #0d1117 35%,
          #080a0e 70%,
          #050608 100%
        );

      color: #f5f7fa;

      font-family: "Inter", sans-serif;

      display: flex;
      flex-direction: column;
      align-items: center;

      padding: 80px 30px 40px;

      position: relative;

      overflow-x: hidden;
    }


    /* =====================================================
       SUBTLE BACKGROUND
       ===================================================== */

    .ambient-light {
      position: fixed;

      width: 700px;
      height: 700px;

      top: -350px;
      left: 50%;

      transform: translateX(-50%);

      background:
        radial-gradient(
          circle,
          rgba(0, 220, 255, 0.055),
          transparent 68%
        );

      pointer-events: none;

      filter: blur(20px);

      z-index: 0;
    }


    /* =====================================================
       HEADER
       ===================================================== */

    header {
      position: relative;

      text-align: center;

      z-index: 2;

      max-width: 900px;
    }

    .system-label {
      font-family: "JetBrains Mono", monospace;

      font-size: 10px;

      letter-spacing: 3px;

      color: #68727d;

      margin-bottom: 22px;
    }

    h1 {
      font-size: clamp(2rem, 5vw, 3.5rem);

      font-weight: 500;

      letter-spacing: -2px;

      color: #f7f9fb;
    }

    .subtitle {
      margin-top: 18px;

      font-size: 14px;

      font-weight: 400;

      color: #7d8792;

      letter-spacing: 0.2px;
    }


    /* =====================================================
       DIVIDER
       ===================================================== */

    .header-line {
      width: min(760px, 80vw);

      height: 1px;

      margin: 45px auto 50px;

      background:
        linear-gradient(
          90deg,
          transparent,
          rgba(255,255,255,0.12),
          transparent
        );
    }


    /* =====================================================
       CARDS
       ===================================================== */

    .cards {
      display: grid;

      grid-template-columns:
        repeat(3, minmax(240px, 290px));

      gap: 18px;

      justify-content: center;

      width: 100%;

      z-index: 2;
    }

    .card {
      position: relative;

      min-height: 190px;

      padding: 34px 28px;

      background:
        rgba(255,255,255,0.025);

      border: 1px solid rgba(255,255,255,0.075);

      border-radius: 18px;

      display: flex;

      flex-direction: column;

      justify-content: center;

      align-items: center;

      text-align: center;

      backdrop-filter: blur(18px);

      -webkit-backdrop-filter: blur(18px);

      transition:
        transform 0.3s ease,
        background 0.3s ease,
        border-color 0.3s ease,
        box-shadow 0.3s ease;
    }

    .card:hover {
      transform: translateY(-5px);

      background:
        rgba(255,255,255,0.045);

      border-color:
        rgba(255,255,255,0.14);

      box-shadow:
        0 18px 50px rgba(0,0,0,0.25);
    }


    /* =====================================================
       CARD LABEL
       ===================================================== */

    .label {
      font-family: "JetBrains Mono", monospace;

      font-size: 9px;

      letter-spacing: 1.8px;

      color: #737d88;

      margin-bottom: 20px;

      text-transform: uppercase;
    }


    /* =====================================================
       CARD VALUE
       ===================================================== */

    .value {
      font-size: 22px;

      font-weight: 500;

      letter-spacing: -0.4px;

      color: #e9edf2;

      min-height: 32px;

      display: flex;

      align-items: center;

      justify-content: center;

      gap: 9px;
    }

    .value::before {
      content: "";

      width: 6px;

      height: 6px;

      border-radius: 50%;

      background: #66717c;

      opacity: 0.7;
    }

    .status-on {
      color: #91e5d2 !important;
    }

    .status-on::before {
      background: #71d8bd;

      box-shadow:
        0 0 12px rgba(113,216,189,0.45);
    }

    .status-off {
      color: #e38b98 !important;
    }

    .status-off::before {
      background: #e38b98;
    }


    /* =====================================================
       FOOTER
       ===================================================== */

    .terminal {
      margin-top: 75px;

      font-family: "JetBrains Mono", monospace;

      font-size: 9px;

      letter-spacing: 1.5px;

      color: #444c55;

      z-index: 2;

      text-align: center;
    }

    .terminal span {
      color: #71808c;
    }


    /* =====================================================
       RESPONSIVE
       ===================================================== */

    @media (max-width: 850px) {

      body {
        padding-top: 55px;
      }

      .cards {
        grid-template-columns:
          minmax(240px, 340px);
      }

      .header-line {
        margin-bottom: 40px;
      }

      .terminal {
        margin-top: 55px;

        text-align: center;
      }
    }


    @media (max-width: 500px) {

      body {
        padding-left: 18px;
        padding-right: 18px;
      }

      h1 {
        font-size: 2rem;

        letter-spacing: -1.5px;
      }

      .subtitle {
        font-size: 13px;
      }
    }

  </style>

</head>


<body>

  <!-- SUBTLE BACKGROUND -->

  <div class="ambient-light"></div>


  <!-- HEADER -->

  <header>

    <div class="system-label">
      SECURE NEURAL INTERFACE - BY THE PROXY CODERS 
    </div>

    <h1>
      ACTULOCK OUTPUT SENTINEL
    </h1>

    <div class="subtitle">
      Real-time system output monitoring
    </div>

    <div class="header-line"></div>

  </header>


  <!-- MAIN CARDS -->

  <div class="cards">


    <!-- RECEIVER -->

    <div class="card">

      <div class="label">
        RECEIVER STATUS
      </div>

      <div
        class="value status-on"
        id="status">

        ONLINE

      </div>

    </div>


    <!-- EVENT -->

    <div class="card">

      <div class="label">
        EVENT DETECTED
      </div>

      <div
        class="value"
        id="event">

        --

      </div>

    </div>


    <!-- PARAMETER -->

    <div class="card">

      <div class="label">
        PARAMETER REQUESTED
      </div>

      <div
        class="value"
        id="param">

        --

      </div>

    </div>


  </div>


  <!-- FOOTER -->

  <div class="terminal">

    <span>ACTULOCK://</span>
    SENTINEL CORE
    //
    ENCRYPTED CHANNEL
    //
    BUILD 07.13

  </div>


  <script>
    async function refresh() {
      try {
        const res = await fetch('/status');
        const data = await res.json();

        // Receiver status card
        const statusEl = document.getElementById('status');
        statusEl.textContent = data.receiving ? 'RECEIVING DATA' : 'NO SIGNAL';
        statusEl.className = 'value ' + (data.receiving ? 'status-on' : 'status-off');

        // Event Detected card -- no visible counting, just the value the
        // backend gives us: the live event, the frozen last value during
        // the silent grace window, or "0" once it's actually been reset.
        const eventEl = document.getElementById('event');
        eventEl.textContent = data.event;
        eventEl.className = 'value' + (data.event === '0' ? ' status-off' : '');

        // Parameter Requested card -- same treatment.
        const paramEl = document.getElementById('param');
        paramEl.textContent = data.param;
        paramEl.className = 'value' + (data.param === '0' ? ' status-off' : '');

      } catch (e) {
        document.getElementById('status').textContent = 'BACKEND UNREACHABLE';
      }
    }

    setInterval(refresh, 800);
    refresh();
  </script>

</body>

</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)


if __name__ == "__main__":
    reader_thread = threading.Thread(target=serial_reader, daemon=True)
    reader_thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False)