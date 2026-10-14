# Hardware mapping

Source: `Adaptive Diagnosis System.fzz`, inspected September 12, 2026.

This document distinguishes connections confirmed by the Fritzing project from
values that must be verified on the physical prototype. Do not energize the
system based only on this document; review the electrical design and component
datasheets first.

## Confirmed components

| Function | Fritzing part/title | Software role |
|---|---|---|
| Host computer | Raspberry Pi 5 | UI, storage, reports, diagnostic engine |
| Real-time controller | Generic `STM32_Nucleo_board` | Sampling, control, safety |
| Motor | 3–12 V DC motor | First diagnostic target |
| Motor control | Cytron MD10C R2 | PWM and direction control |
| Motor monitoring | INA219 — MOTOR | Motor bus voltage/current/power |
| Circuit monitoring | INA219 — Circuit | External-circuit voltage/current/power |
| Temperature | DS18B20 probe | Motor temperature |
| Switching | Two-relay module | Test-path switching/isolation |
| Input power | 12 V, 5 A bench supply | Main supply |
| Conversion | XL4015 CC/CV module | Regulated auxiliary/test supply |
| Distribution | FRC-style power distribution board | Fused branch distribution |
| Voltage probe | 30 kΩ / 10 kΩ divider | Scales probe voltage to 25% |
| Probe protection | BAT54S Schottky clamps, 100 nF capacitor | ADC input protection/filtering |
| Temperature pull-up | 4.7 kΩ resistor | DS18B20 one-wire pull-up |
| Safety | Main, motor, and circuit fuses; kill switch | Hardware protection/shutdown |

## Confirmed STM32 signal groups

The Fritzing netlist contains ten wired STM32 connectors:

- Two connections to the Cytron MD10C control header
- Two connections to the relay module control header
- Six connections routed through the breadboard for sensors and probe circuitry

The custom STM32 part is referenced but not embedded in the `.fzz` archive.
Its connector IDs therefore cannot yet be translated reliably into labeled
pins such as `PA5`, `PB8`, or Arduino-header names. The Cytron custom part also
uses unlabeled connector names, so PWM versus direction must be checked against
the physical board or its source part.

## Important software implications

- Both INA219 boards can share I2C only if they have different addresses.
- The DS18B20 requires a one-wire GPIO and the shown 4.7 kΩ pull-up.
- The motor driver requires distinct PWM and direction outputs.
- Relay outputs may be active-low; startup firmware must default them to the
  electrically safe state.
- A 30 kΩ/10 kΩ divider gives a ratio of 0.25. With a 3.3 V ADC this corresponds
  to an ideal 13.2 V full-scale input before tolerances and clamp headroom.
- RPM and vibration measurements exist in the software model but no RPM or
  vibration sensor is present in this Fritzing file. They must remain optional
  until those sensors are added.
- The Raspberry Pi 5 is present in the drawing but has no wired data connection
  in the Fritzing netlist. USB serial remains the proposed Pi–STM32 link, not a
  connection confirmed by this file.

## Information still required before firmware pin definitions

1. Exact Nucleo model; the project currently identifies only a generic Nucleo.
2. STM32 pin label for each of the ten connected signals.
3. Which MD10C control terminal is PWM and which is direction.
4. INA219 I2C addresses and which controller reads them.
5. Relay channel purpose and whether each input is active-low.
6. Fuse current ratings and the physical kill-switch behavior.
7. ADC reference and intended maximum voltage-probe input.
8. The desired USB serial port settings and message rate.

## Proposed Pi–STM32 measurement frame

The firmware should publish newline-delimited JSON initially:

```json
{"type":"measurement","seq":1,"time_ms":1250,"motor_voltage_v":11.92,"motor_current_a":0.84,"circuit_voltage_v":5.01,"circuit_current_a":0.12,"temperature_c":36.5,"pwm_percent":65.0,"direction":"forward","relay_mask":0,"faults":[]}
```

RPM and vibration fields should be omitted or set to `null` until the associated
hardware exists. Commands should use separate messages with sequence numbers and
acknowledgements; motor-enable commands must be rejected when a hardware safety
fault is active.
