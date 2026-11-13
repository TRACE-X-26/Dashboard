# TRACE-X direct motor requests

Motor Start Test now submits a request without a separate software authorization
step. Stop Test, emergency stop, ADS v1 JSON/CRC32 framing, and live run telemetry
remain available. This is a source update: no board was flashed or motor energized.
Existing unrelated workspace edits were preserved.

## Every gate removed from the motor request path

| Layer | Removed gate | Result |
|---|---|---|
| Motor dashboard | `profile_ready` and `hardware_control` prerequisites on Start | A failed/missing configuration snapshot does not disable Start. |
| Motor dashboard | Mandatory Check hardware / cached preflight | Check remains optional and read-only. |
| Motor dashboard | Supervision checkbox and confirmation dialog | Direct Start sends one request. Physical cutoff remains necessary. |
| Motor dashboard | Required load, condition, and mass prompt sequence | Unknown metadata stays UNKNOWN/null; no physical condition is invented. |
| Motor dashboard | Pi fixed-PWM approval locks on PWM choices | All implemented PWM presets can be requested; the STM32 can still reject a duty outside its fixed-duty build. |
| Motor dashboard | Profile maximum duration used to disable Start | Basic finite 0.1–30 second input bounds remain; actual firmware maximum remains enforced locally. |
| Diagnostic dashboard | Status fetch, physical confirmation dialog, mandatory condition prompts for hardware starts | Motor starts no longer depend on that extra UI flow. |
| Pi startup | Hardware-mode opt-in and strict circuit profile validation before backend startup | Hardware mode starts without those flags; circuit start still validates its own policy. Invalid circuit enable flag becomes a warning with circuit output disabled. |
| Pi motor runtime | `ADS_HARDWARE_CONTROL_ENABLED` opt-in | An explicit motor request enables its command transport; circuit power keeps its own opt-in. |
| Pi motor runtime | `operator_authorized`, `supervised_confirmed` flags as authorization prerequisites | Omitted/false flags no longer reject motor requests. Compatibility fields remain accepted. No true operator confirmation is manufactured. |
| Pi profile | Required profile file, object, commissioning evidence, calibration ID, asset/fixture/firmware metadata | Missing/malformed metadata becomes visible warnings. Missing physical USB routing still fails honestly. |
| Pi profile | Wiring/relay/cutoff/communication/calibration/operator/protection/feedback/supervision attestation flags | Pi metadata does not authorize physical readiness; the actual STM32 retains its physical acceptance checks. |
| Pi profile | Temperature retirement, supply topology, relay polarity, electrical policy/limit metadata validation | Invalid Pi configuration becomes warnings. Critical actual firmware capabilities are still checked independently. |
| Pi motor runtime | Requested asset ID must equal commissioned asset ID | Request metadata no longer blocks physical command dispatch. USB serial identity and protocol device identity still route the actual controller. |
| Pi catalog | Cached preflight readiness, one approved PWM, individual procedure approval | Implemented motor procedures are selectable without those approvals. Unsupported procedures remain unavailable. |
| Pi orchestration | Fresh human confirmation for each supervised procedure / single-procedure rule | A requested supported sequence can execute under one owner. Each individual motor run remains bounded by the MCU. |
| Pi orchestration | Required load/condition metadata and minimum five-second observation window for hardware procedures | Missing context or too-short analysis windows produce insufficient analysis rather than blocking capture. |
| Pi orchestration | Remembered idle Circuit selection | A motor request selects Motor under the shared owner lock. Active circuit operations still exclude motor use. |
| Pi contract | Exact equality with Pi firmware version, mode, PWM, duration, feedback/temperature/relay/sensing configuration | Metadata mismatch is advisory. CRC, critical electrical/power-check/watchdog/duration capabilities remain required. |
| Pi acquisition | Host telemetry stale/invalid quality or unverified calibration as motor gates | Quality is journaled and displayed. The STM32 still requires valid fresh calibrated electrical protection locally. |
| Pi acquisition | Stationary/RPM data as an idle hardware request gate | Optional encoder quality is advisory; the MCU retains checks on known calibrated motion. |
| STM32 acceptance | Optional temperature calibration and optional thermal configuration as board acceptance requirements | Missing optional temperature cannot disable motor output permission. Electrical calibration is still mandatory. |
| STM32 readiness | Missing optional encoder/temperature acquisitions | Electrical validity, age, synchronization and limits continue to determine electrical protection readiness. |
| STM32 idle readiness | Invalid encoder or uncalibrated encoder nonzero reading | Uncalibrated/missing encoder cannot deny the request. Valid calibrated motion still denies a stationary power check. |
| STM32 protected motor handshake | Repeated software supervision flag on ARM/START | Protected motor requests use the physical checks and zero-PWM power handshake. Circuit supervision confirmation remains unchanged. |

Missing baseline data never authorized motor output before this change and remains
analysis-only. It now also appears as a visible warning; no baseline or health
score is fabricated. Raw null/invalid measurements remain null/invalid. Firmware
feedback installation, output permission, PWM, faults, and stop confirmation are
never inferred from UI selection or a Pi attestation.

## Every retained protection and necessary constraint

- Physical emergency power cutoff and installed power-feedback interlocks remain
  unchanged. Normal and supervised firmware retain their existing physical
  acceptance paths. This update does not establish that a physical cutoff works.
- STM32 `EMERGENCY_STOP` still stops output and latches lockout. STOP remains
  idempotent and acts even in a disabled build or with an old sequence number.
- STM32 electrical shutdown still enforces 10–14 V and a trip at absolute current
  >=1.5 A in the protected profile. No voltage/current thresholds were weakened.
- Calibrated electrical sensing, valid fresh synchronized voltage/current/power
  acquisitions, and electrical protection acceptance remain mandatory on the MCU.
  Stale local electrical sensing still shuts down even if stale Pi telemetry is
  only a warning. Optional temperature retains its trip for a valid calibrated
  reading at/above its configured limit.
- The downstream relay-on power check still holds PWM at zero, requires a powered
  acquisition after its 50 ms settling interval, and fails after 1500 ms. Supply
  faults never authorize motor PWM.
- STM32 heartbeat-loss stop remains 2000 ms. Independent motor-driver watchdog,
  main-loop IWDG reset, UART receive error/overflow fault handling and shutdown
  latches remain unchanged. Late heartbeat cannot hide an expired deadline.
- STM32 controller and output driver retain their configured maximum test duration,
  with a hard ceiling of 30000 ms. The Pi also rejects requests outside 100–30000 ms.
- Boot starts with output off. ARM is explicit; no heartbeat/reconnect auto-start.
  Relay reset/polarity/wiring, cutoff, communication-stop, protection-limit,
  electrical calibration and physical output build acceptance remain in firmware.
- The STM32 retains fixed FORWARD direction and its compiled fixed PWM duty. A
  different supported dashboard preset can be requested, but the firmware returns
  its actual `PWM_OUT_OF_RANGE` rejection. No output range was expanded.
- Motor/circuit relay exclusion, one serial owner, backend ownership locks,
  cancellation, and disconnect cleanup remain. Leaving the active run stream
  requests cancellation. USB identity must resolve to exactly one intended board.
- ADS v1 CRC32, device identity, sequence correlation, anti-replay, fresh heartbeat
  before ARM, start acknowledgment/event validation and confirmed zero-output stop
  acknowledgment remain. There is no simulated fallback in a hardware request.
- The Pi verifies actual firmware critical protection capabilities independently
  of Pi metadata, and stops on fresh calibrated out-of-range electrical data as
  secondary protection. Unsupported procedures and malformed requests remain
  rejected; selecting a label does not implement an unsupported hardware test.
- Circuit power retains its separate profile, authorization, supervision, branch
  exclusion, deadline and shutdown rules.

## Acknowledgments and protocol

The motor sequence remains:
`GET_CAPABILITIES / GET_STATUS -> heartbeat -> ARM_TEST -> PREPARE_TEST_POWER ->
POWER_READY at zero PWM -> SET_PWM -> START_TEST -> STOP_TEST`.
The wire format and command names are unchanged across dashboard/Pi/STM32.

Each command acknowledgment is retained with its decoded result and original
CRC-protected protocol frame in the run journal and exposed to the UI as
`firmware_acknowledgments`. A rejected START/SET_PWM remains visible alongside the
later cleanup STOP reply; accepted replies are not synthesized. Firmware stop
reasons are preserved in terminal failure messages. Serial device-error replies
and transport failures appear as run errors; a Pi stop request does not claim
physical stop until the STM32 acknowledges zero output.

An older STM32 image may still require its original confirmation behavior. Its
rejection is displayed rather than being silently overridden. Deploy the updated
firmware sources together with the updated Pi backend/dashboard for the relaxed
optional-sensor and motor-confirmation behavior.

## Deployment and verification

Rebuild the frontend and install the updated Python sources on the Pi. Configure
`ADS_AUTOMATION_HARDWARE_PROFILE` with the actual `serial_identity`; unknown
identity is a connection error, not a hardware-ready claim. No new opt-in flag is
needed for an explicit motor request. The circuit-power opt-in is unchanged.

Example reproducible firmware builds (no programmer is invoked):

```sh
make -C ADS OUT=../build/stm32-direct-default -j4
make -C ADS BENCH_PROFILE=bench/downstream.operator.h OUT=../build/stm32-direct-protected -j4
```

The existing protected operator profile is used as supplied; its attestations
are not independent bench verification. Physical bring-up remains unverified.
The corresponding sources in `FinalFirmware/ADS` were updated too; its pre-existing default protection-attestation setting was preserved rather than equated with bench evidence; archived original
reference inputs and older installer archives were not rewritten.

Validation completed: all 228 tests pass (`.venv/bin/python -m unittest discover -s tests`); frontend TypeScript/Vite build and ESLint pass; Python API/engine tests;
host C production controller/protocol/acquisition/protection/relay tests; real ARM
builds of the default and protected profiles. New host C regressions exercise
both firmware source trees with absent optional sensors, provisional encoder
readings, overcurrent, under/overvoltage, invalid/stale electrical data, direct
motor ARM without software confirmation, the required power-check handshake and
emergency-stop lockout. These are software tests, not evidence of a physical run.

## All source files modified by this task

| Files | Change |
|---|---|
| `.env.example` | Correct motor versus circuit authorization guidance. |
| `README.md` | Point current runtime instructions at this report. |
| `api/main.py` | Advisory profile warnings in hardware status. |
| `diagnostic_platform/config.py` | Remove hardware-mode startup/strict profile gates; surface invalid circuit enable flags as warnings. |
| `diagnostic_platform/automated_engine.py` | Direct motor requests, warnings, acquisition quality, actual acknowledgments/reasons. |
| `diagnostic_platform/hardware_runtime.py` | Motor-specific transport permission and independent critical protection contract. |
| `diagnostic_platform/test_registry.py` | Remove commissioning/PWM/procedure approval gates for supported requests. |
| `frontend/src/App.tsx` | Remove extra hardware start confirmation/status/prompt flow. |
| `frontend/src/HardwareMotorControls.tsx` | Direct controls, advisory warnings and firmware acknowledgments. |
| `frontend/src/api.ts` | Hardware status warning response type. |
| `frontend/src/types.ts` | Run acknowledgment/warning and telemetry quality types. |
| `ADS/Core/Inc/ads_board_config.h` | Remove optional thermal acceptance prerequisites. |
| `ADS/Core/Src/ads_sensors.c` | Optional encoder/temperature readiness independent of electrical protection. |
| `ADS/Core/Src/ads_test.c` | Protected motor handshake without repeated software supervision flag. |
| `FinalFirmware/ADS/Core/Inc/ads_board_config.h` | Matching firmware package change. |
| `FinalFirmware/ADS/Core/Src/ads_sensors.c` | Matching firmware package change. |
| `FinalFirmware/ADS/Core/Src/ads_test.c` | Matching firmware package change. |
| `tests/bounded_motor_harness.c` | Protected supervised motor fixture mode. |
| `tests/optional_motor_sensors_harness.c` | New production sensor-readiness regression harness. |
| `tests/test_direct_motor_firmware.py` | New optional-sensor and protected direct-start regressions. |
| `tests/test_architecture.py` | Hardware-mode startup without circuit opt-in. |
| `tests/test_automated_api.py` | Accepted hardware request with honest missing-transport failure. |
| `tests/test_automated_engine.py` | Supported request availability without approval flags. |
| `tests/test_hardware_runtime.py` | Warnings, acknowledgments, direct start, optional telemetry, retained shutdown tests. |
| `tests/test_motor_dashboard_integration.py` | Advisory calibration/temperature metadata expectations. |
| `tests/test_operator_motor_build.py` | Advisory profile parsing while preserving existing user changes. |
| `tests/test_protection.py` | Advisory Pi topology metadata; retain firmware electrical tests. |
| `tests/test_supervised_mode.py` | Advisory Pi mode metadata and direct request expectations. |
| `docs/SOFTWARE_PREFLIGHT_REMOVAL.md` | This complete change/protection/file report. |

Generated validation outputs: `frontend/dist/`, `frontend/tsconfig.app.tsbuildinfo` and
`frontend/tsconfig.node.tsbuildinfo` (if regenerated by TypeScript), `build/stm32-direct-default/`, and
`build/stm32-direct-protected/`. These are build products, not flashed images.
Pre-existing IDE settings, launch files, `main.h`, downstream documentation,
other FinalFirmware files and STM32 workspace files were not changed by this task.
