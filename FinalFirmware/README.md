# TRACE-X FinalFirmware 2.0

**STM32 Nucleo-F401RE** firmware workspace for Dashboard 2.0.

* Complete STM32CubeIDE/C firmware project: `ADS/`
* Original user-supplied ZIP and legacy motor source: `reference/`
* Revision details and wiring lock: `FIRMWARE_CHANGES.md`
* Clone source and branch: `SOURCE.txt`

**No 12 V output is enabled by installation.** Do not flash the board's old
code over this project or alter GPIO/firmware safety gates to force a motor run.

The existing Dashboard FastAPI backend sends ADS v1/CRC32 requests, not the
legacy human-readable text protocol. This project intentionally keeps the
current ADS firmware identity/protocol. It has the motor relay/PWM power-check
and dual-INA219 logic already; the new source guard enforces the agreed mapping.

## Build (on Mac with STM32CubeIDE)

Import `ADS/` into STM32CubeIDE as an existing project. Verify that the managed
project/build uses the OUTPUT-DISABLED protected profile. The supplied default
Makefile may also build a disabled ELF if the STM32 ARM toolchain path matches:

```
cd "$HOME/Documents/ChatGPT/Capstone/FinalFirmware"
make -C ADS OUT=../build/final-disabled BENCH_PROFILE=bench/protected.example.h
```

This is a compile check, not permission to flash an enabled physical-output
image. Note the relative OUT/BENCH_PROFILE variables are interpreted from ADS/.

## Required commissioning before a supervised physical run

1. Check 12V fused supply, independent branch wiring, common ground, driver input,
   motor connections, power cutoff, relay contact and logic-level interface.
2. Confirm relay COM-LOW active-LOW behavior AND inactive HIGH during reset.
3. Confirm motor INA219 is 0x40, circuit INA219 is **0x41** (A0 soldered).
   A1 soldered may produce a different address and requires a hardware review.
4. Confirm effective flashed image's firmware identity and safe outputs via
   read-only ADS GET_CAPABILITIES/GET_STATUS/READ_MEASUREMENTS.
5. Verify calibrated current/voltage feedback and the exact 10-14 V, 1.5A
   bounds, then verify stop, watchdog, deadline and physical cutoff on the bench.
6. Configure the Pi hardware profile and USB identity to match the firmware,
   without fabricating acceptance flags. Dashboard UI may hide complicated
   checklists but cannot automatically mark unverified protections as passed.

## Dashboard action

The simplest frontend is a large Start / Stop panel. Internally, keep the
existing multi-command Pi engine: ARM_TEST -> PREPARE_TEST_POWER -> validate
fresh powered voltage/current at PWM=0 -> SET_PWM -> START_TEST, and STOP_TEST.
Do not send raw UART text commands or actuate directly from the browser.

**Status:** packaged firmware source only; not flashed, electrically verified,
or compiled on a real STM32. The GitHub base is the current documented source,
not evidence of what is presently on the Pi/MCU.
