#ifndef TEST_HAL_H
#define TEST_HAL_H
#include <stdint.h>
typedef struct { unsigned port; } GPIO_TypeDef;
extern GPIO_TypeDef test_gpio_a, test_gpio_b;
#define GPIOA (&test_gpio_a)
#define GPIOB (&test_gpio_b)
#define GPIO_PIN_4 (1U << 4)
#define GPIO_PIN_5 (1U << 5)
#define GPIO_PIN_8 (1U << 8)
#define GPIO_PIN_10 (1U << 10)
#define GPIO_MODE_INPUT 0U
#define GPIO_MODE_OUTPUT_PP 1U
#define GPIO_NOPULL 0U
#define GPIO_SPEED_FREQ_LOW 0U
typedef enum { GPIO_PIN_RESET, GPIO_PIN_SET } GPIO_PinState;
typedef struct { uint32_t Pin, Mode, Pull, Speed; } GPIO_InitTypeDef;
typedef struct { volatile uint32_t CR1, CCER, CCR3; } TIM_TypeDef;
extern TIM_TypeDef test_tim2;
#define TIM2 (&test_tim2)
#define TIM_CCER_CC3E (1U << 8)
#define TIM_CR1_CEN 1U
void test_enable_tim2(void);
#define __HAL_RCC_TIM2_CLK_ENABLE() test_enable_tim2()
uint32_t HAL_GetTick(void);
void test_enable_gpio_b(void);
#define __HAL_RCC_GPIOB_CLK_ENABLE() test_enable_gpio_b()
void HAL_GPIO_WritePin(GPIO_TypeDef *, uint16_t, GPIO_PinState);
void HAL_GPIO_Init(GPIO_TypeDef *, GPIO_InitTypeDef *);
#endif
