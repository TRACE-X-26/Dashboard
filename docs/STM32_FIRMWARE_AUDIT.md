# STM32 Firmware and `.ioc` Audit

**Inspected:** October 14, 2026  
**Project:** `/Users/markussanford/ADS`  
**Board:** NUCLEO-F401RE / STM32F401RET6  
**Firmware modification during this phase:** None

## Authoritative files inspected

- `ADS.ioc`
- `Core/Src/main.c`
- `Core/Inc/main.h`
- `Core/Src/stm32f4xx_hal_msp.c`
- `Core/Inc/stm32f4xx_hal_conf.h`
- STM32CubeIDE project metadata and F401RE linker scripts

The application repository did not contain firmware. The existing STM32CubeIDE project was found separately at `/Users/markussanford/ADS` and was treated as read-only.

## Actual configured peripherals

| Peripheral | Configuration | Status |
|---|---|---|
| USART2 | Asynchronous TX/RX on PA2/PA3 | **IMPLEMENTED_UNVERIFIED** |
| GPIO PA5 | Nucleo LD2 green LED, push-pull output | **IMPLEMENTED_UNVERIFIED** |
| GPIO PC13 | Nucleo B1 pushbutton, falling-edge interrupt mode | **IMPLEMENTED_UNVERIFIED** |
| SWD/SWO | PA13, PA14, PB3 | Debug configuration |
| ADC | Not configured; HAL module disabled | **UNSUPPORTED** |
| I²C | Not configured; HAL module disabled | **UNSUPPORTED** |
| Timer/PWM | Not configured; HAL timer module disabled | **UNSUPPORTED** |
| RPM input/capture | Not configured | **UNSUPPORTED** |
| Relay outputs | Not configured | **UNSUPPORTED** |
| Watchdog | Not configured | **UNSUPPORTED** |

## Actual pin map

| STM32 pin | `.ioc` label/function | Existing use |
|---|---|---|
| PA2 | `USART_TX` / USART2_TX | STM32-to-ST-LINK virtual COM transmit |
| PA3 | `USART_RX` / USART2_RX | ST-LINK virtual COM-to-STM32 receive; firmware does not read it |
| PA5 | `LD2 [Green Led]` | Initialized low; no application behavior |
| PC13 | `B1 [Blue PushButton]` | Configured input/EXTI; no application handler behavior |
| PA13 | TMS/SWDIO | Debug |
| PA14 | TCK/SWCLK | Debug |
| PB3 | SWO | Debug trace |

There is currently **no assigned PWM pin and no assigned MD10C direction pin**. No pin should be selected from the Fritzing image or earlier proposals without updating and reviewing `ADS.ioc`.

## Serial configuration

The generated `MX_USART2_UART_Init` function is authoritative for runtime serial settings:

- USART: USART2
- Baud: 115200
- Data bits: 8
- Parity: none
- Stop bits: 1
- Hardware flow control: none
- Oversampling: 16
- GPIO mode: alternate-function push-pull, AF7
- Transfer implementation: blocking `HAL_UART_Transmit`
- Receive interrupt/DMA: not implemented

On the Nucleo board this USART is connected through the ST-LINK virtual COM port. A typical Raspberry Pi device path is `/dev/ttyACM0`, but the actual enumerated path must be confirmed using the Pi, not assumed.

## Existing application behavior

The main loop sends the following ASCII line once per second:

```text
STM32 CONNECTED TO PI\r\n
```

It does not parse incoming bytes, emit JSON, acknowledge commands, publish measurements, or control the motor. The new backend includes a bounded `probe_legacy_banner()` operation to recognize this exact line without transmitting anything.

## Configuration discrepancy

`ADS.ioc` records an external HSE clock source and 84 MHz derived clock values, while the generated `SystemClock_Config()` in `main.c` selects HSI as the PLL source. This suggests the generated code and `.ioc` clock selection may not be synchronized. Do not regenerate code until this discrepancy is reviewed, because regeneration could alter working clock behavior.

## Preservation decision

The firmware was not edited because it lacks all motor/sensor capabilities required by the target protocol. Adding command parsing before pin selection, watchdog design, motor-power protection, and sensor wiring verification would create unjustified control risk. The Raspberry Pi implementation is tested against a simulation adapter until a separate firmware phase is approved.

