#ifndef ADS_MOTOR_H
#define ADS_MOTOR_H
#include <stdint.h>

/* Wiring-design confirmation is not electrical acceptance. NO/COM is wired,
 * but the trigger jumper, GPIO levels and reset behavior require bench tests.
 * All motor commands remain disabled even if these board checks are approved. */
#define ADS_RELAY_NO_COM_DESIGN_CONFIRMED 1
#ifndef ADS_RELAY_POWER_PATH_VERIFIED
#define ADS_RELAY_POWER_PATH_VERIFIED 0
#endif
#ifndef ADS_RELAY_POLARITY_VERIFIED
#define ADS_RELAY_POLARITY_VERIFIED 0
#endif
#ifndef ADS_RELAY_SAFE_OUTPUT_VERIFIED
#define ADS_RELAY_SAFE_OUTPUT_VERIFIED 0
#endif
#ifndef ADS_RELAY_ACTIVE_LEVEL
#define ADS_RELAY_ACTIVE_LEVEL (-1)
#endif
#ifndef ADS_RELAY_INACTIVE_LEVEL
#define ADS_RELAY_INACTIVE_LEVEL (ADS_RELAY_ACTIVE_LEVEL == -1 ? -1 : 1 - ADS_RELAY_ACTIVE_LEVEL)
#endif
/* Preserve the earlier board-configuration name; it must agree with inactive. */
#ifndef ADS_RELAY_DISCONNECT_LEVEL
#define ADS_RELAY_DISCONNECT_LEVEL ADS_RELAY_INACTIVE_LEVEL
#endif
#if (ADS_RELAY_POWER_PATH_VERIFIED != 0 && ADS_RELAY_POWER_PATH_VERIFIED != 1) || \
    (ADS_RELAY_POLARITY_VERIFIED != 0 && ADS_RELAY_POLARITY_VERIFIED != 1) || \
    (ADS_RELAY_SAFE_OUTPUT_VERIFIED != 0 && ADS_RELAY_SAFE_OUTPUT_VERIFIED != 1)
#error "Relay verification flags must be 0 or 1"
#endif
#if ADS_RELAY_POWER_PATH_VERIFIED && ADS_RELAY_DISCONNECT_LEVEL != 0 && ADS_RELAY_DISCONNECT_LEVEL != 1
#error "A verified design requires an explicit relay disconnect level (0 or 1)"
#endif
#if ADS_RELAY_POLARITY_VERIFIED && \
    ((ADS_RELAY_ACTIVE_LEVEL != 0 && ADS_RELAY_ACTIVE_LEVEL != 1) || \
     ADS_RELAY_INACTIVE_LEVEL != 1 - ADS_RELAY_ACTIVE_LEVEL)
#error "Verified relay polarity requires opposite active/inactive binary levels"
#endif
#if ADS_RELAY_DISCONNECT_LEVEL != ADS_RELAY_INACTIVE_LEVEL
#error "Relay disconnect level must match inactive level"
#endif
#define ADS_MOTOR_RELAY_VERIFIED (ADS_RELAY_POWER_PATH_VERIFIED && \
    ADS_RELAY_POLARITY_VERIFIED && ADS_RELAY_SAFE_OUTPUT_VERIFIED)
#define ADS_MOTOR_WATCHDOG_TIMEOUT_MS 2000U

void ADS_Motor_Init(void);
/* Idempotent, nonblocking; callable before Init/from faults. Disables TIM2 CH3,
 * holds PB10 low and requests PB5 de-energization only with verified config.
 * No contact/supply feedback: this never confirms physical power removal. */
void ADS_Motor_Stop(void);
void ADS_Motor_Fault(void);
/* STM32-local communication watchdog, independent of Pi/UI scheduling.
 * Poll is also called from SysTick. Neither heartbeat nor Stop clears a latch.
 * Init is startup-only, never a remote fault recovery operation. */
void ADS_Motor_Heartbeat(uint32_t now_ms);
void ADS_Motor_Poll(uint32_t now_ms);
int ADS_Motor_IsLatched(void);
int ADS_Motor_RelayConfigured(void);
#endif
