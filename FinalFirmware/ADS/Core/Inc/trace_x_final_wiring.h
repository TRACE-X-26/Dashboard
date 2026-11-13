#ifndef TRACE_X_FINAL_WIRING_H
#define TRACE_X_FINAL_WIRING_H
/* TRACE-X 2.0: compile-time pin/protocol guard, based on working main.h
   and current ADS GitHub wiring. This does not enable physical outputs. */
#include "main.h"
#include "ads_board_config.h"
#include "ads_motor.h"
_Static_assert(MOTOR_RELAY_Pin == GPIO_PIN_5, "Motor relay must be PB5 / IN1");
_Static_assert(CIRCUIT_RELAY_Pin == GPIO_PIN_4, "Circuit relay must be PB4 / IN2");
_Static_assert(MOTOR_PWM_Pin == GPIO_PIN_10, "TIM2 CH3 PWM must be PB10");
_Static_assert(MOTOR_DIRECTION_Pin == GPIO_PIN_8, "Direction must be PA8");
#if ADS_MOTOR_INA219_ADDRESS != 0x40U || ADS_CIRCUIT_INA219_ADDRESS != 0x41U
#error "Motor/circuit INA219 expected at 0x40 / 0x41; confirm A0/A1 hardware"
#endif
#if ADS_RELAY_ACTIVE_LEVEL != 0 || ADS_RELAY_INACTIVE_LEVEL != 1
#endif
#if ADS_CIRCUIT_RELAY_ACTIVE_LEVEL != 0
#error "Circuit relay must use verified COM-LOW jumper: LOW=ON"
#endif
#if ADS_BENCH_PWM_PERCENT != 50U || ADS_BENCH_MAX_DURATION_MS > 30000U
#error "The supervised motor profile must remain fixed at 50 percent, <=30 seconds"
#endif
#if ADS_ELECTRICAL_LIMITS_ENABLED != 1
#error "Motor electrical protections must remain enabled"
#endif
#endif /* TRACE_X_FINAL_WIRING_H */
