# Software-Defined Diagnostic Platform

This repository contains the Raspberry Pi software for a modular electrical and
electromechanical diagnostic platform. The first supported device is a DC motor.

The current milestone runs without activating hardware. It generates realistic
simulated measurements, calculates derived values, applies multi-sensor
diagnostic rules, and provides the same status/measurement/command interface as
the disabled physical STM32 serial adapter.

## Run it

Python 3.11 or newer is recommended. Install the backend dependencies before
running the API or physical serial adapter.

```bash
python3 -m diagnostic_platform --scenario healthy --samples 5
python3 -m diagnostic_platform --scenario overloaded --samples 5
python3 -m diagnostic_platform --scenario stalled --samples 3
python3 -m diagnostic_platform --scenario communication_loss --samples 6
python3 -m unittest discover -s tests
```

## React + FastAPI application

The primary application uses a React/TypeScript frontend and FastAPI backend.

Backend terminal:

```bash
source .venv/bin/activate
python3 -m pip install -r requirements-backend.txt
python3 -m uvicorn api.main:app --reload --port 13115
```

Frontend terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. FastAPI also exposes interactive API documentation
at `http://localhost:13115/docs`.

Runtime configuration is read from environment variables. Copy `.env.example`
as a reference; simulation remains the safe default. Hardware and replay modes
are intentionally rejected until their runtime adapters are configured and
verified.

## STM32 USB serial boundary

The Raspberry Pi backend now contains a modular STM32 connection and a matching
simulation adapter. The physical transport is configured for the settings found
in the generated firmware: `/dev/ttyACM0`, 115200 baud, 8 data bits, no parity,
1 stop bit, and no flow control. The proposed application protocol uses one
versioned JSON message per line and supports status, capabilities, measurements,
commands, acknowledgments, device errors, and heartbeats.

For a communication-only Raspberry Pi test, connect the Nucleo through its
ST-LINK USB port and run:

```bash
source .venv/bin/activate
python3 -m diagnostic_platform.verify_stm32
```

The tester prefers a stable `/dev/serial/by-id/` path and falls back to
`/dev/ttyACM*`. It requests only status, capabilities, faults, and heartbeat;
motor control remains disabled. An explicit port may be supplied with
`--port /dev/ttyACM0`.

The existing STM32 firmware was inspected but not changed. It currently sends
`STM32 CONNECTED TO PI` once per second on USART2 through the ST-LINK virtual COM
port. It does not yet parse commands or configure PWM, motor direction, ADC,
RPM, or a communication watchdog. For that reason, selecting physical hardware
and issuing real motor commands remain disabled. The simulator is the supported
development path until the firmware, wiring, voltage levels, current limiting,
emergency stop, and safe-loss-of-communication behavior pass the documented
checks.

See [the firmware audit](docs/STM32_FIRMWARE_AUDIT.md), [serial protocol](docs/SERIAL_PROTOCOL.md),
[firmware integration plan](docs/STM32_INTEGRATION_PLAN.md),
[hardware verification plan](docs/HARDWARE_VERIFICATION.md), and [Phase 2 review guide](docs/PHASE_2_REVIEW.md).

The existing STM32CubeIDE project is stored in `ADS/`. Its current incremental
firmware implements only safe protocol parsing and read-only status operations.
It builds successfully in STM32CubeIDE, but has not been flashed or verified on
hardware. Generated build output and the local `TraceX.app` bundle are excluded
from Git; the CubeIDE project metadata, source, HAL/CMSIS dependencies, startup
code, linker scripts, and `.ioc` remain available for normal MacBook use.

The backend provides REST endpoints for profiles and history plus a WebSocket
endpoint for live diagnostic tests. The frontend includes the system dashboard,
real-time graphs, explainable findings, test history, and profile management.

### Motor control simulator

The **Motor control** screen provides enable/disable control, forward/reverse
selection, PWM speed commands, an automated ramp sequence, live simulated motor
feedback, and a latched emergency stop. Commands travel through FastAPI and
receive explicit accepted/rejected acknowledgments. Backend safety interlocks
block PWM while disabled, block direction changes while the motor is turning,
and block all output until a latched emergency stop is reset. This API boundary
is designed to remain stable when the simulator is replaced by the STM32 serial
transport.

The automated PWM ramp is owned by the backend rather than browser timers. It
is bounded to ten steps and always disables simulated motor output when it
completes or is cancelled. Motor commands and sequence actions are recorded in
the SQLite system-event log.

### Live multimeter

The **Live multimeter** screen samples all planned sensing paths twice per
second, provides hold and clear controls, plots the selected signal, and tracks
minimum, average, and maximum values. Its channels map directly to motor INA219,
circuit INA219, external voltage-divider probe, and DS18B20 temperature sensor
inputs. Values are simulated now; the frontend contract can remain unchanged
when real sensor readings arrive from the STM32.

### Guided circuit diagnostics

The **Circuit diagnostics** workspace implements a test-point workflow for the
protected 12 V load circuit. Learn Mode captures known-healthy behavior;
Diagnose Mode guides the operator through supply, fuse, current, and resistance
checks and compares each reading with specification or learned limits. Built-in
simulation faults include a blown fuse, open load, shorted load, and supply
voltage drop, each producing an explainable final conclusion.

### Adaptive baseline workflow

1. Run a test using a known-healthy motor.
2. Open **Test history** and select the completed test.
3. Choose **Use this test as healthy baseline**.
4. Future tests for that device are compared with its learned current and RPM
   behavior in addition to the rated specification limits.

The first two samples are treated as the motor startup window. After that
window, a critical diagnostic finding triggers a software safety stop and the
session is saved with the `SAFETY_TRIP` state.

## Legacy Streamlit prototype

Create a virtual environment, install the UI dependencies, and launch the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

The prototype includes a system dashboard, live simulated motor tests, scenario fault
injection, diagnostic results, SQLite-backed test history, charts, and editable
device profiles.

Available scenarios are `healthy`, `overloaded`, `undervoltage`, `overheating`,
`stalled`, `sensor_failure`, and `communication_loss`. Each completed run is
stored in `diagnostics.db` unless `--database` specifies another path.

## Architecture

```text
MeasurementSource (stateful simulator now, STM32 serial later)
        -> MotorMeasurement
        -> MotorDiagnosticEngine + MotorProfile
        -> MotorTestRunner state machine
        -> DiagnosticReport + SQLite history
        -> CLI now, GUI/reports later
```

## Recommended next milestones

1. Review the Phase 2 simulator and communication tests.
2. Confirm MD10C and sensor pin assignments plus 3.3 V signal compatibility.
3. Implement the documented protocol in firmware with motor output off at boot.
4. Verify USB communication with motor power disconnected.
5. Complete electrical safety, calibration, stop, and watchdog tests before any
   physical motor command is enabled.
