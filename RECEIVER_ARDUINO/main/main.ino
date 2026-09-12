/*
  ActuLock -- RECEIVER Arduino (Node 2)
  Board: Arduino Nano

  Receives the relayed decision line from the SENDER (Input) Arduino
  over SoftwareSerial, identifies which of the 3 simulated events it
  belongs to, drives its own LED, and reports a clean line over USB
  to Laptop B -- this prints automatically to the Arduino IDE Serial
  Monitor with no extra code, and is also what nodes/output_dashboard.py
  reads to render it as a live webpage.

  Wiring to the SENDER Arduino:
    Receiver D10 (SoftSerial RX) <- Sender D11 (SoftSerial TX)
    Receiver D11 (SoftSerial TX) -> Sender D10 (SoftSerial RX)  [optional return path]
    Receiver GND                  -- Sender GND   <-- MUST be shared or nothing works

  Line received from the Sender (see docs/protocol.md):
    EVENT:<id>,DECISION:<APPROVE|DENY>,PARAM:<value>

  Line sent to Laptop B over USB serial, 9600 baud:
    EVENT_DETECTED:<NAME>|DECISION:<APPROVE|DENY>|PARAM:<value>

  NOTE: Sender (Input Arduino) firmware is not included yet -- holding
  off until the backend code is finalized, per instructions. This
  sketch is complete and self-contained on its own; it just won't
  receive anything real until the Sender side exists.
*/

#include <SoftwareSerial.h>

const int GREEN_LED_PIN = 6;
const int RED_LED_PIN   = 7;
SoftwareSerial linkSerial(10, 11); // RX, TX <- from Sender Arduino

const int EVENT_COUNT = 3;
const char* EVENT_NAMES[EVENT_COUNT] = {
  "IV_BLOOD_PUMP",  // id 1
  "ROBOTIC_ARM",    // id 2
  "DAM_GATE"        // id 3
};

String inputBuffer = "";

void setup() {
  Serial.begin(9600);      // USB to Laptop B
  linkSerial.begin(9600);  // link from Sender Arduino
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  Serial.println("ActuLock RECEIVER node online.");
}

void loop() {
  while (linkSerial.available() > 0) {
    char c = linkSerial.read();
    if (c == '\n') {
      handleLine(inputBuffer);
      inputBuffer = "";
    } else if (c != '\r') {
      inputBuffer += c;
    }
  }
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;