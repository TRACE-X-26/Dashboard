# Implementation Checklist

Status values: `TODO`, `IN PROGRESS`, `SOFTWARE PASS`, `HARDWARE VERIFIED`, `BLOCKED`, `DEFERRED`.

## Phase 0 — repository audit

- [x] Inspect repository source and configuration — **SOFTWARE PASS**
- [x] Preserve existing uncommitted files — **SOFTWARE PASS**
- [x] Run backend tests — **SOFTWARE PASS (26/26)**
- [x] Run frontend build and lint — **SOFTWARE PASS**
- [x] Run dependency integrity checks — **SOFTWARE PASS**
- [x] Exercise simulation CLI — **SOFTWARE PASS**
- [x] Document architecture, roadmap, hardware capabilities, and test plan — **SOFTWARE PASS**
- [ ] Create first Git baseline — **TODO; user workflow decision required**

## Phase 1 — modular architecture

- [x] Validated runtime settings — **SOFTWARE PASS**
- [x] Shared measurement envelope — **SOFTWARE PASS**
- [x] Source, quality, and calibration metadata — **SOFTWARE PASS**
- [x] Hardware/simulation/replay interfaces — **SOFTWARE PASS**
- [x] Unified test orchestrator — **SOFTWARE PASS**
- [x] Backend-owned automated sequence — **SOFTWARE PASS; SIMULATION ONLY**
- [x] Structured and persisted event logging — **SOFTWARE PASS**
- [ ] Frontend component-test framework — **DEFERRED TO QA PHASE; build and lint pass**

## Phase 2 — STM32 communication boundary

- [x] Inspect existing `.ioc` and generated firmware without modification — **SOFTWARE PASS**
- [x] Record actual USB serial settings and pin assignments — **SOFTWARE PASS**
- [x] Define versioned status/measurement/command/error protocol — **SOFTWARE PASS**
- [x] Implement bounded timeouts and correlated responses — **SOFTWARE PASS**
- [x] Implement safe serial disconnection — **SOFTWARE PASS; PHYSICAL FIRMWARE NOT COMPATIBLE YET**
- [x] Implement simulation adapter — **SOFTWARE PASS**
- [x] Keep hardware mode and motor output disabled — **SOFTWARE PASS**
- [x] Add protocol and adapter tests — **SOFTWARE PASS (46/46 total backend tests)**
- [ ] Implement protocol in STM32 firmware — **BLOCKED: pin/electrical/safety review**
- [ ] Exercise protocol over physical USB serial — **BLOCKED: compatible firmware and hardware authorization**

## Hardware readiness

- [x] Existing STM32 pin/configuration audit — **SOFTWARE PASS; PA2/PA3 USART2, PA5 LD2, PC13 button recorded**
- [ ] Final MD10C/sensor pin map — **BLOCKED: not present in `.ioc`; wiring verification required**
- [ ] STM32 command/measurement firmware — **BLOCKED: current firmware only transmits a legacy banner**
- [x] Mock serial protocol — **SOFTWARE PASS**
- [ ] Physical e-stop evidence — **BLOCKED: hardware**
- [ ] Sensor calibration evidence — **BLOCKED: hardware**
- [ ] Low-power motor test — **BLOCKED: preceding safety gates**

## Demonstration deliverables

- [ ] Reliable motor diagnostic workflow — **IN PROGRESS: simulation only**
- [ ] Versioned approved baseline workflow — **TODO**
- [ ] CSV export — **TODO**
- [ ] PDF report — **TODO**
- [ ] Public simulation/private hardware separation — **TODO**
- [ ] Backup replay dataset — **TODO**
