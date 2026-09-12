# ActuLock
**Hardware-Enforced Trust for Agentic AI**
> AI proposes. ActuLock verifies. Hardware executes.

## What it does
An AI agent's intent (simulated as JSON) is checked by a Python policy
engine. Only if approved does a signal reach the Arduino, which
independently controls power to the actuator. A denial never reaches
the hardware as an action.

## Architecture
AI Agent (JSON) → Policy Engine (Python) → Arduino (hardware guardian) → Actuator

## Repo structure
- `agent/` — simulated AI intent files (valid / malicious / e-stop)
- `policy/policy_engine.py` — reads intent, checks policy, sends decision
- `policy/policy.json` — rules + serial port config
- `firmware/arduino_nano/main.ino` — receives decision, switches actuator power

## Setup
1. `pip install pyserial`
2. Upload `main.ino` to the Arduino
3. Set your serial port in `policy.json`
4. Run: `python policy/policy_engine.py agent/mock_intent_valid.json`

## Demo
- Valid request → approved → actuator powers on
- Malicious request → denied → reason logged, actuator stays off
- Bypass attempt sent directly to hardware → still rejected independently

## Status
Built: policy engine, hardware-side enforcement, audit logging.
Ahead: crypto-signed commands, sensor input, LLM interface, dashboard.