/* Synthetic acquisitions exercise the production readiness code; no hardware. */
#include <assert.h>
#ifndef SENSOR_SOURCE
#define SENSOR_SOURCE "../ADS/Core/Src/ads_sensors.c"
#endif
#include SENSOR_SOURCE
static uint32_t tick=100;
static int power;
uint32_t HAL_GetTick(void) { return tick; }
int ADS_Motor_PowerState(void) { return power; }
int main(void)
{
  ADS_Sensors_Init();
  for(unsigned i=0;i<3;i++)cache.channels[i]=(ADS_Sample){0,tick,1};
  /* Missing encoder and uncalibrated/missing optional temperature do not gate. */
  assert(!cache.channels[4].valid && !cache.channels[3].valid);
  assert(ADS_Motor_IdleReady());
  cache.channels[4]=(ADS_Sample){123000,tick,1};
  assert(ADS_Motor_IdleReady()); /* Uncalibrated encoder is advisory even if nonzero. */
  cache.channels[0].milli_value=12000;power=3;
  assert(ADS_Sensors_Ready());
  cache.channels[1].milli_value=1500;assert(!ADS_Sensors_Ready());
  cache.channels[1].milli_value=0;
  cache.channels[0].milli_value=9999;assert(!ADS_Sensors_Ready());
  cache.channels[0].milli_value=14001;assert(!ADS_Sensors_Ready());
  cache.channels[0].milli_value=12000;
  cache.channels[1].valid=0;assert(!ADS_Sensors_Ready());
  cache.channels[1].valid=1;tick+=1501;
  assert(!ADS_Sensors_Ready());assert(!ADS_Motor_IdleReady());
  return 0;
}
