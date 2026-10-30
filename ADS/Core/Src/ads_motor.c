#include "main.h"
#include "ads_motor.h"

static volatile uint32_t last_heartbeat_ms;
static volatile uint8_t watchdog_ready;
static volatile uint8_t shutdown_latched;

void ADS_Motor_Stop(void)
{
  GPIO_InitTypeDef gpio = {0};
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* PB10 is TIM2 CH3. Disable the channel and timer before changing the pad;
   * clearing CCR3 alone is insufficient when compare preload is enabled. */
  __HAL_RCC_TIM2_CLK_ENABLE();
  TIM2->CCER &= ~TIM_CCER_CC3E;
  TIM2->CR1 &= ~TIM_CR1_CEN;
  TIM2->CCR3 = 0U;

  HAL_GPIO_WritePin(MOTOR_PWM_GPIO_Port, MOTOR_PWM_Pin, GPIO_PIN_RESET);
  gpio.Pin = MOTOR_PWM_Pin;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(MOTOR_PWM_GPIO_Port, &gpio);

  gpio.Pin = MOTOR_RELAY_Pin;
#if ADS_MOTOR_RELAY_VERIFIED
  /* Preload before switching the pin to output; never pulse the other level. */
  HAL_GPIO_WritePin(MOTOR_RELAY_GPIO_Port, MOTOR_RELAY_Pin,
                   ADS_RELAY_DISCONNECT_LEVEL ? GPIO_PIN_SET : GPIO_PIN_RESET);
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
#else
  /* Unknown relay polarity: neither low nor high nor a pull is assumed safe.
   * Reset-time disconnection requires a verified external fail-safe circuit. */
  gpio.Mode = GPIO_MODE_INPUT;
#endif
  HAL_GPIO_Init(MOTOR_RELAY_GPIO_Port, &gpio);
}

void ADS_Motor_Init(void)
{
  /* Direction is deliberately left at its reset configuration. No direction
   * or start operation is available until physical acceptance is complete. */
  ADS_Motor_Stop();
  /* A fault arriving before initialization must stay latched. Static storage
   * is reset only by MCU reset; there is no software rearm operation. */
  if (!watchdog_ready) last_heartbeat_ms = HAL_GetTick();
  watchdog_ready = 1U;
}

void ADS_Motor_Fault(void)
{
  shutdown_latched = 1U;
  ADS_Motor_Stop();
}

void ADS_Motor_Poll(uint32_t now_ms)
{
  if (watchdog_ready && !shutdown_latched &&
      (uint32_t)(now_ms - last_heartbeat_ms) >= ADS_MOTOR_WATCHDOG_TIMEOUT_MS)
  {
    shutdown_latched = 1U;
    ADS_Motor_Stop();
  }
}

void ADS_Motor_Heartbeat(uint32_t now_ms)
{
  /* Check the OLD deadline first, so a late heartbeat cannot hide a timeout. */
  ADS_Motor_Poll(now_ms);
  if (watchdog_ready && !shutdown_latched) last_heartbeat_ms = now_ms;
}

int ADS_Motor_IsLatched(void)
{
  return shutdown_latched != 0U;
}

int ADS_Motor_RelayConfigured(void)
{
  return ADS_MOTOR_RELAY_VERIFIED;
}
