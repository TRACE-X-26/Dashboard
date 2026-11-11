# Motor data integration and temperature removal

Temperature is excluded from motor diagnostic rules, baseline fitting/scoring features, automated-run health requirements, charts, metric cards, profile controls and multimeter channels. Original files and legacy database fields remain readable for provenance. The physical operator profile already disables temperature. No firmware output configuration was changed.

## Archive audit

The supplied trace_x_motor_data.zip and earlier motor_test_results.zip contain 134 CSV entries, representing 74 unique byte contents and 60 exact duplicate copies. All entries are accounted for. Tests 2–13 contain measurements; Test 1 has a software-only result. Separate repeated recordings remain separate. Filename load labels remain unverified labels in grams. Friction condition, motor identity and calibration are not inferred from filenames. The workbook is a secondary human-readable view with six sheets; its claimed source inventory differs from the CSV-only inventory and is not used to override original recordings.

The supplied motor_data_collector.py is a passive logger. It does not execute motor commands. Its MEAS branch has device ticks and shunt microvolts, while its generic nested JSON handling cannot establish validity of ADS measurement objects. It is not substituted for the exclusive CRC-protected backend owner.

Run the repeatable audit/import from the checkout:

```sh
python3 -m diagnostic_platform.experimental_data /path/to/trace_x_motor_data.zip /path/to/motor_test_results.zip --output data/motor_audit --database diagnostics.db
```

Outputs include canonical.json with parsed rows, quality flags, provenance and per-run statistics; run_features.csv; archive_replay.json for the existing CSV recordings screen; summary.json when stdout is redirected; and originals/ containing exact source CSV bytes under their SHA-256. Re-import uses existing database content hashes. The generated dataset is local and excluded by the existing data policy. The replay endpoint prefers the audited replay; ADS_MOTOR_DATA_DIR can override the directory.

Mean, median, minimum, maximum, population standard deviation and median absolute deviation are calculated per run and per channel, separately for all recorded observations and logged running phases. Adjacent serial lines are not converted into instantaneous power. Serial-reported power stays reported. Host event markers do not establish STM32 acquisition phase. Each run remains historical reference only. There are no approved baselines or validated ML predictions in this archive. Statistical prediction intervals cannot be justified from unknown operating conditions.

## Supervised execution

The current upstream engine already supports bounded fixed-duty execution with single serial ownership, authorization, cancellation, STOP acknowledgment, heartbeat loss handling, local deadlines and durable samples/events. This change preserves the operator-approved 50% PWM, 30-second maximum, 1.5 A cutoff and 11–13 V window. The serial identity still needs completion on the Pi. No hardware was flashed or energized. Historical catalog names have been corrected; catalog membership does not authorize other procedures.

## Update the Pi

Use the Pi desktop account and preserve local edits before pulling. The existing installation is /home/amirzoom8/Trace-X.

```sh
cd /home/amirzoom8/Trace-X
systemctl --user stop trace-x.service
python3 -c 'import sqlite3,time; s=sqlite3.connect("diagnostics.db"); d=sqlite3.connect("diagnostics.backup-"+time.strftime("%Y%m%d-%H%M%S")+".db"); s.backup(d); d.close(); s.close()'
git pull --ff-only origin trace-x-integration-2026-10-30
.venv-pi/bin/python -m pip install -r requirements-backend.txt
(cd frontend && npm ci && npm run build)
.venv-pi/bin/python -m diagnostic_platform.experimental_data ~/Downloads/trace_x_motor_data.zip ~/Downloads/motor_test_results.zip --output data/motor_audit --database diagnostics.db
.venv-pi/bin/python -c 'from pathlib import Path; from diagnostic_platform.automated_engine import load_hardware_profile; p=load_hardware_profile(Path.home()/".config/trace-x/motor-hardware.json"); print(p["operating_mode"],p["limits"])'
systemctl --user restart trace-x.service
curl --fail http://127.0.0.1:13115/api/health
journalctl --user -u trace-x.service -n 40 --no-pager
```

The source changes must be published before the pull commands obtain them. Review the live profile against the flashed firmware and retain per-run supervision. These commands update application software and data only.

## Remaining requirements

No physical test was verified by this agent. No healthy-run approvals, validated numeric health index, ML accuracy, fixture torque model, validated startup peak capture or new physical load/friction actuator is supplied. Load and friction remain operator-applied procedures. Further work is needed to expand the procedure registry, approve matched electrical/RPM baselines, establish full operating context and support the broader fault-comparison and training requirements in the original request.
