#include "ads_protocol.h"

#include <stdio.h>

static uint32_t simulated_tick_ms = 100U;

static int capture_transmit(const uint8_t *data, size_t length, void *context)
{
  (void)context;
  return fwrite(data, 1U, length, stdout) == length ? 0 : -1;
}

static uint32_t get_tick(void *context)
{
  (void)context;
  return simulated_tick_ms++;
}

int main(void)
{
  ADS_Protocol protocol;
  int input;

  ADS_Protocol_Init(&protocol, capture_transmit, get_tick, NULL);
  while ((input = getchar()) != EOF)
  {
    ADS_Protocol_ProcessByte(&protocol, (uint8_t)input);
  }
  return 0;
}
