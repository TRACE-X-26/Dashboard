# FinalFirmware 2.0 — firmware change record

The supplied legacy `main.c` was a useful functional starting point but was not
suitable as the runtime image: it started the motor automatically, printed mixed
plain text and ADS v1 messages, only read INA219 0x40, and preloaded both relay
pins LOW without a verified safe startup sequence.

The complete replacement base is TRACE-X-26/Dashboard's ADS project, which
already implements the required updates:
* PB5/D4 motor relay IN1 and PB4/D5 circuit relay IN2; COM-LOW, HIGH=OFF.
* PWM PB10/D6 TIM2 CH3 and direction PA8/D7; encoder PA6/PC7.
* 0x40 MOTOR, 0x41 CIRCUIT INA219 on PB8/PB9 I2C1.
* No automatic PWM on boot. UART2/ST-LINK at 115200 baud, ADS JSON v1/CRC32.
* Explicit supervised ARM -> PREPARE_TEST_POWER -> power validation at zero PWM
  -> SET_PWM -> START_TEST, enforced by Pi engine/STM32, then STOP_TEST.
* Hardware output disabled in the default build, independent firmware timeout,
  10-14V and <1.5A protected motor profile (bench validation still needed).

This migration adds a TRACE-X 2.0 source-level wiring/limits guard in
`ADS/Core/Inc/trace_x_final_wiring.h` and includes it from ADS/Core/Src/main.c.
It intentionally DOES NOT change the ADS wire protocol, firmware version, or
physical output permission. This ensures the existing Pi backend can recognize
the same firmware contract, rather than breaking communication again.

IMPORTANT: Hardware startup and coil-driver input levels must be verified.
The GPIO status is not relay contact feedback. A physical cutoff and suitable
fuses/current limiting are required. The circuit sensor jumper MUST be checked:
this configuration uses A0-bridged 0x41, not A1-bridged 0x44.

Original user-supplied source archived under `reference/` outside `ADS/`.
The final touchscreen UI can be dramatically simplified without removing the
firmware safety interlocks. Do not remove CRC, watchdog, relay exclusion, or
current/voltage limit enforcement merely to make a Start button available.
