from __future__ import annotations

import asyncio
import csv
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from diagnostic_platform.config import Settings
from diagnostic_platform.history import parse_csv
from diagnostic_platform.live import LiveMonitor
from diagnostic_platform.control import (
    SimulatedMotorController,
    SimulatedMotorSequenceService,
    serialize_control_state,
)
from diagnostic_platform.circuits import CircuitDiagnosticService
from diagnostic_platform.measurements import DataSource, motor_measurement_envelopes
from diagnostic_platform.models import MotorProfile
from diagnostic_platform.multimeter import SimulatedMultimeter
from diagnostic_platform.sources import SimulatedMotorSource
from diagnostic_platform.storage import DiagnosticStore
from diagnostic_platform.stm32 import DeviceResponseError, SimulatedSTM32Connection
from diagnostic_platform.workflow import MotorTestSession, TestState, TestStoppedError

from .schemas import (
    CircuitRunPayload,
    MotorCommandPayload,
    ProfilePayload,
    STM32CommandPayload,
    TestRequest,
    HistoricalImportPayload,
)
from .dashboard import mount_dashboard


ROOT = Path(__file__).resolve().parents[1]
settings = Settings.from_environment(ROOT)
logger = logging.getLogger("adaptive_diagnostic_system")
logger.setLevel(getattr(logging, settings.log_level))
DATABASE_PATH = settings.database_path
motor_controller = SimulatedMotorController()
motor_sequence = SimulatedMotorSequenceService(motor_controller)
stm32_connection = SimulatedSTM32Connection(motor_controller)
multimeter = SimulatedMultimeter()
circuit_service = CircuitDiagnosticService()
live_monitor = LiveMonitor(os.getenv('ADS_LIVE_SERIAL_PORT', '').strip(), settings.serial_baud)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_store() -> DiagnosticStore:
    return DiagnosticStore(DATABASE_PATH)


def record_event(event_type: str, severity: str = "INFO", **details: object) -> None:
    try:
        with open_store() as store:
            store.add_event(now(), event_type, severity, details)
    except Exception:
        logger.exception("Unable to persist system event %s", event_type)


def serialize_row(row) -> dict:
    return dict(row)


def serialize_measurement(measurement) -> dict:
    return {
        "sequence": measurement.sequence,
        "timestamp": measurement.timestamp.isoformat(),
        "voltage": measurement.voltage,
        "current": measurement.current,
        "rpm": measurement.rpm,
        "temperature": measurement.temperature,
        "resistance": measurement.resistance,
        "vibration_rms": measurement.vibration_rms,
        "input_power": measurement.input_power,
    }


def serialize_report(report) -> dict:
    return {
        "device_id": report.device_id,
        "health_score": report.health_score,
        "condition": report.condition,
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity.value,
                "message": finding.message,
                "possible_causes": list(finding.possible_causes),
            }
            for finding in report.findings
        ],
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    store = open_store()
    try:
        if not store.list_profiles():
            store.save_profile(MotorProfile("MOTOR-001", 12, 2, 2500, 1.2, 3, 80))
    finally:
        store.close()
    record_event("APPLICATION_STARTED", mode=settings.mode, hardware_control=False)
    stm32_connection.connect()
    live_monitor.start()
    try:
        yield
    finally:
        live_monitor.close()
        stm32_connection.disconnect()


app = FastAPI(
    title="Adaptive Diagnostic System API",
    version="0.6.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.mode,
        "database": DATABASE_PATH.name,
        "hardware_control": False,
        "measurement_source": settings.mode.upper(),
        "stm32_connected": stm32_connection.is_connected(),
    }


@app.get('/api/live/status')
def live_status() -> dict:
    return live_monitor.snapshot()


@app.websocket('/ws/live')
async def live_updates(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(live_monitor.snapshot())
            await asyncio.sleep(.25)
    except WebSocketDisconnect:
        return


@app.get("/api/hardware/status")
def hardware_status() -> dict:
    return stm32_connection.status()


@app.get("/api/hardware/capabilities")
def hardware_capabilities() -> dict:
    capabilities = stm32_connection.capabilities()
    return {
        "device_id": capabilities.device_id,
        "measurement_types": list(capabilities.measurement_types),
        "commands": list(capabilities.commands),
        "firmware_version": capabilities.firmware_version,
        "source": "SIMULATION",
        "hardware_verified": False,
    }


@app.get("/api/hardware/measurements")
def hardware_measurements() -> dict:
    return stm32_connection.read_measurements()


@app.post("/api/hardware/commands")
def hardware_command(payload: STM32CommandPayload) -> dict:
    try:
        result = stm32_connection.execute(payload.command, payload.arguments)
    except (ValueError, DeviceResponseError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_event(
        "STM32_SIMULATION_COMMAND",
        command=payload.command,
        arguments=payload.arguments,
        source="SIMULATION",
    )
    return {"result": result, "source": "SIMULATION", "hardware_control": False}


@app.get("/api/motor/status")
def motor_status() -> dict:
    state = motor_controller.snapshot()
    telemetry = motor_controller.telemetry()
    return {
        "state": serialize_control_state(state),
        "telemetry": telemetry.__dict__,
        "mode": settings.mode,
        "sequence": motor_sequence.status().__dict__,
    }


@app.post("/api/motor/commands")
def motor_command(payload: MotorCommandPayload) -> dict:
    if payload.action in {"disable", "emergency_stop"} and motor_sequence.status().running:
        motor_sequence.cancel()
    acknowledgment = motor_controller.command(
        payload.command_id, payload.action, payload.value
    )
    record_event(
        "MOTOR_COMMAND",
        "INFO" if acknowledgment.accepted else "WARNING",
        command_id=payload.command_id,
        action=payload.action,
        value=payload.value,
        accepted=acknowledgment.accepted,
        message=acknowledgment.message,
        source="SIMULATION",
    )
    return {
        "command_id": acknowledgment.command_id,
        "accepted": acknowledgment.accepted,
        "message": acknowledgment.message,
        "state": serialize_control_state(acknowledgment.state),
    }


@app.post("/api/motor/sequences/pwm-ramp")
def start_motor_sequence() -> dict:
    accepted, message = motor_sequence.start()
    logger.info("simulation_sequence_start accepted=%s message=%s", accepted, message)
    record_event("MOTOR_SEQUENCE_STARTED", "INFO" if accepted else "WARNING", accepted=accepted, message=message, source="SIMULATION")
    return {"accepted": accepted, "message": message, "sequence": motor_sequence.status().__dict__}


@app.post("/api/motor/sequences/cancel")
def cancel_motor_sequence() -> dict:
    accepted, message = motor_sequence.cancel()
    logger.info("simulation_sequence_cancel was_running=%s", accepted)
    record_event("MOTOR_SEQUENCE_CANCELLED", was_running=accepted, message=message, source="SIMULATION")
    return {"accepted": accepted, "message": message, "sequence": motor_sequence.status().__dict__}


@app.get("/api/multimeter/readings")
def multimeter_readings() -> dict:
    state = motor_controller.snapshot()
    return multimeter.read(state, motor_controller.telemetry())


@app.get("/api/circuits/profiles")
def circuit_profiles() -> dict:
    return {
        "profiles": circuit_service.list_profiles(),
        "scenarios": list(circuit_service.SCENARIOS),
    }


@app.post("/api/circuits/run")
def run_circuit_test(payload: CircuitRunPayload) -> dict:
    try:
        return circuit_service.run(payload.profile_id, payload.mode, payload.scenario)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/scenarios")
def scenarios() -> list[str]:
    return list(SimulatedMotorSource.SCENARIOS)


@app.get("/api/baselines")
def list_baselines() -> list[dict]:
    with open_store() as store:
        return [baseline.__dict__ for baseline in store.list_baselines()]


@app.get("/api/profiles")
def list_profiles() -> list[dict]:
    store = open_store()
    try:
        return [profile.__dict__ for profile in store.list_profiles()]
    finally:
        store.close()


@app.post("/api/profiles", status_code=201)
def save_profile(payload: ProfilePayload) -> dict:
    profile = MotorProfile(**payload.model_dump())
    store = open_store()
    try:
        store.save_profile(profile)
    finally:
        store.close()
    return profile.__dict__


@app.get("/api/sessions")
def list_sessions(limit: int = 100) -> list[dict]:
    store = open_store()
    try:
        return [serialize_row(row) for row in store.list_sessions(max(1, min(limit, 500)))]
    finally:
        store.close()


@app.get("/api/events")
def list_events(limit: int = 100) -> list[dict]:
    with open_store() as store:
        return store.list_events(max(1, min(limit, 500)))


@app.get("/api/recordings")
def list_recordings() -> list[dict]:
    with open_store() as store:
        return store.list_recordings()


@app.post("/api/recordings", status_code=201)
def import_recording(payload: HistoricalImportPayload) -> dict:
    metadata = payload.model_dump(exclude={"content"})
    try:
        result = parse_csv(payload.content, metadata)
    except (ValueError, TypeError, AttributeError, csv.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with open_store() as store:
        recording_id = store.save_recording(payload.content, result, now())
        return store.recording(recording_id)


@app.get("/api/recordings/{recording_id}")
def get_recording(recording_id: int) -> dict:
    with open_store() as store:
        try:
            return store.recording(recording_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Recording not found") from exc


@app.get("/api/sessions/{session_id}")
def get_session(session_id: int) -> dict:
    store = open_store()
    try:
        try:
            summary = serialize_row(store.session_summary(session_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Test session not found") from exc
        return {
            "summary": summary,
            "measurements": [serialize_row(row) for row in store.session_measurements(session_id)],
            "findings": [serialize_row(row) for row in store.session_findings(session_id)],
        }
    finally:
        store.close()


@app.post("/api/sessions/{session_id}/baseline", status_code=201)
def create_baseline(session_id: int) -> dict:
    with open_store() as store:
        try:
            baseline = store.create_baseline(session_id, now())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Test session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return baseline.__dict__


@app.websocket("/ws/tests")
async def run_test(websocket: WebSocket) -> None:
    await websocket.accept()
    store: DiagnosticStore | None = None
    session: MotorTestSession | None = None
    try:
        request = TestRequest.model_validate(await websocket.receive_json())
        if request.scenario not in SimulatedMotorSource.SCENARIOS:
            await websocket.send_json({"type": "error", "message": "Unknown simulation scenario"})
            await websocket.close(code=1008)
            return
        store = open_store()
        try:
            profile = store.get_profile(request.device_id)
        except KeyError:
            await websocket.send_json({"type": "error", "message": "Device profile not found"})
            await websocket.close(code=1008)
            return

        source = SimulatedMotorSource(profile, request.scenario, seed=42)
        session = MotorTestSession(source, store)
        session_id = session.start(profile, request.scenario)
        await websocket.send_json(
            {"type": "started", "session_id": session_id, "total_samples": request.samples}
        )
        for _ in range(request.samples):
            sample = session.acquire()
            envelopes = motor_measurement_envelopes(
                sample.measurement,
                device_id=profile.device_id,
                source=DataSource.SIMULATION,
                session_id=session_id,
            )
            await websocket.send_json(
                {
                    "type": "measurement",
                    "measurement": serialize_measurement(sample.measurement),
                    "measurement_envelopes": [item.to_dict() for item in envelopes],
                    "report": serialize_report(sample.report),
                    "source": DataSource.SIMULATION.value,
                }
            )
            session.enforce_safety(sample)
            if request.interval_ms:
                await asyncio.sleep(request.interval_ms / 1000)

        final_report = session.complete()
        await websocket.send_json(
            {"type": "completed", "session_id": session_id, "report": serialize_report(final_report)}
        )
    except TestStoppedError as exc:
        await websocket.send_json(
            {
                "type": "failed",
                "state": exc.state.value,
                "message": str(exc),
                "report": serialize_report(exc.sample.report),
            }
        )
    except TimeoutError as exc:
        await websocket.send_json(
            {"type": "failed", "state": "COMMUNICATION_FAULT", "message": str(exc)}
        )
    except WebSocketDisconnect:
        if session is not None and session.state not in {TestState.COMPLETE, TestState.SAFETY_TRIP}:
            session.fail(TestState.TEST_ABORTED)
    except Exception:
        logger.exception("Diagnostic WebSocket failed")
        if session is not None:
            session.fail(TestState.FAILED)
        await websocket.send_json({"type": "error", "message": "Diagnostic test failed"})
    finally:
        if session is not None:
            session.close()
        if store is not None:
            store.close()


if os.getenv('ADS_SERVE_DASHBOARD', '') == '1':
    mount_dashboard(app, ROOT / 'frontend' / 'dist')
