from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path

from .models import DiagnosticReport, MotorBaseline, MotorMeasurement, MotorProfile


class DiagnosticStore:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            PRAGMA journal_mode = WAL;
            PRAGMA busy_timeout = 5000;
            CREATE TABLE IF NOT EXISTS device_profiles (
                device_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                scenario TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                state TEXT NOT NULL,
                condition TEXT,
                health_score INTEGER,
                FOREIGN KEY(device_id) REFERENCES device_profiles(device_id)
            );
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                voltage REAL, current REAL, rpm REAL, temperature REAL,
                resistance REAL, vibration_rms REAL,
                FOREIGN KEY(session_id) REFERENCES test_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES test_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS motor_baselines (
                device_id TEXT PRIMARY KEY,
                source_session_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                voltage_mean REAL NOT NULL,
                current_mean REAL NOT NULL,
                rpm_mean REAL NOT NULL,
                temperature_mean REAL NOT NULL,
                current_std REAL NOT NULL,
                rpm_std REAL NOT NULL,
                FOREIGN KEY(device_id) REFERENCES device_profiles(device_id),
                FOREIGN KEY(source_session_id) REFERENCES test_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_measurements_session
                ON measurements(session_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_sessions_device
                ON test_sessions(device_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON system_events(id DESC);
            """
        )

    def __enter__(self) -> DiagnosticStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def save_profile(self, profile: MotorProfile) -> None:
        payload = json.dumps(profile.__dict__, separators=(",", ":"))
        self.connection.execute(
            "INSERT OR REPLACE INTO device_profiles VALUES (?, ?)",
            (profile.device_id, payload),
        )
        self.connection.commit()

    def start_session(self, profile: MotorProfile, scenario: str, started_at: str) -> int:
        self.save_profile(profile)
        cursor = self.connection.execute(
            "INSERT INTO test_sessions(device_id, scenario, started_at, state) VALUES (?, ?, ?, 'RUNNING')",
            (profile.device_id, scenario, started_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def add_measurement(self, session_id: int, m: MotorMeasurement) -> None:
        self.connection.execute(
            """INSERT INTO measurements(
                session_id, sequence, timestamp, voltage, current, rpm,
                temperature, resistance, vibration_rms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, m.sequence, m.timestamp.isoformat(), m.voltage, m.current,
             m.rpm, m.temperature, m.resistance, m.vibration_rms),
        )

    def complete_session(self, session_id: int, report: DiagnosticReport, completed_at: str) -> None:
        self.connection.execute(
            "UPDATE test_sessions SET completed_at=?, state='COMPLETE', condition=?, health_score=? WHERE id=?",
            (completed_at, report.condition, report.health_score, session_id),
        )
        for finding in report.findings:
            self.connection.execute(
                "INSERT INTO findings(session_id, code, severity, message) VALUES (?, ?, ?, ?)",
                (session_id, finding.code, finding.severity.value, finding.message),
            )
        self.connection.commit()

    def fail_session(self, session_id: int, state: str, completed_at: str) -> None:
        self.connection.execute(
            "UPDATE test_sessions SET completed_at=?, state=? WHERE id=?",
            (completed_at, state, session_id),
        )
        self.connection.commit()

    def session_summary(self, session_id: int) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT s.*, COUNT(m.id) AS sample_count FROM test_sessions s LEFT JOIN measurements m ON m.session_id=s.id WHERE s.id=? GROUP BY s.id",
            (session_id,),
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return row

    def list_sessions(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """SELECT s.*, COUNT(m.id) AS sample_count
                FROM test_sessions s
                LEFT JOIN measurements m ON m.session_id=s.id
                GROUP BY s.id ORDER BY s.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        )

    def session_measurements(self, session_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM measurements WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        )

    def session_findings(self, session_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT code, severity, message FROM findings WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        )

    def list_profiles(self) -> list[MotorProfile]:
        rows = self.connection.execute(
            "SELECT profile_json FROM device_profiles ORDER BY device_id"
        ).fetchall()
        return [MotorProfile(**json.loads(row["profile_json"])) for row in rows]

    def get_profile(self, device_id: str) -> MotorProfile:
        row = self.connection.execute(
            "SELECT profile_json FROM device_profiles WHERE device_id=?", (device_id,)
        ).fetchone()
        if row is None:
            raise KeyError(device_id)
        return MotorProfile(**json.loads(row["profile_json"]))

    def create_baseline(self, session_id: int, created_at: str) -> MotorBaseline:
        summary = self.session_summary(session_id)
        if summary["state"] != "COMPLETE":
            raise ValueError("Only a completed test can become a baseline")
        if summary["condition"] != "HEALTHY":
            raise ValueError("Only a healthy test can become a baseline")
        rows = self.session_measurements(session_id)
        required = ("voltage", "current", "rpm", "temperature")
        if not rows or any(row[name] is None for row in rows for name in required):
            raise ValueError("Baseline test contains missing measurements")

        def values(name: str) -> list[float]:
            return [float(row[name]) for row in rows]

        current = values("current")
        rpm = values("rpm")
        baseline = MotorBaseline(
            device_id=summary["device_id"],
            created_at=created_at,
            sample_count=len(rows),
            voltage_mean=statistics.fmean(values("voltage")),
            current_mean=statistics.fmean(current),
            rpm_mean=statistics.fmean(rpm),
            temperature_mean=statistics.fmean(values("temperature")),
            current_std=statistics.pstdev(current),
            rpm_std=statistics.pstdev(rpm),
        )
        self.connection.execute(
            """INSERT INTO motor_baselines(
                device_id, source_session_id, created_at, sample_count,
                voltage_mean, current_mean, rpm_mean, temperature_mean,
                current_std, rpm_std
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                source_session_id=excluded.source_session_id,
                created_at=excluded.created_at,
                sample_count=excluded.sample_count,
                voltage_mean=excluded.voltage_mean,
                current_mean=excluded.current_mean,
                rpm_mean=excluded.rpm_mean,
                temperature_mean=excluded.temperature_mean,
                current_std=excluded.current_std,
                rpm_std=excluded.rpm_std""",
            (baseline.device_id, session_id, baseline.created_at, baseline.sample_count,
             baseline.voltage_mean, baseline.current_mean, baseline.rpm_mean,
             baseline.temperature_mean, baseline.current_std, baseline.rpm_std),
        )
        self.connection.commit()
        return baseline

    def get_baseline(self, device_id: str) -> MotorBaseline | None:
        row = self.connection.execute(
            """SELECT device_id, created_at, sample_count, voltage_mean,
            current_mean, rpm_mean, temperature_mean, current_std, rpm_std
            FROM motor_baselines WHERE device_id=?""",
            (device_id,),
        ).fetchone()
        return None if row is None else MotorBaseline(**dict(row))

    def list_baselines(self) -> list[MotorBaseline]:
        rows = self.connection.execute(
            """SELECT device_id, created_at, sample_count, voltage_mean,
            current_mean, rpm_mean, temperature_mean, current_std, rpm_std
            FROM motor_baselines ORDER BY device_id"""
        ).fetchall()
        return [MotorBaseline(**dict(row)) for row in rows]

    def add_event(
        self, timestamp: str, event_type: str, severity: str, details: dict
    ) -> int:
        cursor = self.connection.execute(
            "INSERT INTO system_events(timestamp, event_type, severity, details_json) VALUES (?, ?, ?, ?)",
            (timestamp, event_type, severity, json.dumps(details, separators=(",", ":"))),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_events(self, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, timestamp, event_type, severity, details_json FROM system_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "severity": row["severity"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        ]

    def close(self) -> None:
        self.connection.close()
