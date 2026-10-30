#ifndef ADS_PROTOCOL_H
#define ADS_PROTOCOL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>
#include <stdint.h>

#define ADS_PROTOCOL_VERSION 1U
#define ADS_PROTOCOL_MAX_FRAME_BYTES 512U
#define ADS_PROTOCOL_HEARTBEAT_TIMEOUT_MS 2000U

/* Set to 1 only for the pre-Phase-2 plain-text banner behavior. */
#define ADS_PROTOCOL_LEGACY_BANNER_ENABLED 0U

typedef int (*ADS_ProtocolTransmitFn)(const uint8_t *data, size_t length,
                                      void *context);
typedef uint32_t (*ADS_ProtocolTickFn)(void *context);

/* Order: voltage, current, power, temperature, RPM. Fixed point in 1/1000 unit.
 * Acquisition must be nonblocking and mark missing/stale/CRC-failed data invalid. */
typedef struct { int32_t milli_value; uint32_t timestamp_ms; uint8_t valid; } ADS_Sample;
typedef void (*ADS_AcquireFn)(ADS_Sample samples[5], void *context);
typedef void (*ADS_StopFn)(void *context);
typedef void (*ADS_HeartbeatFn)(uint32_t now_ms, void *context);

typedef enum
{
  ADS_PROTOCOL_SAFE_IDLE = 0,
  ADS_PROTOCOL_COMMUNICATION_TIMEOUT
} ADS_ProtocolSafetyState;

typedef struct
{
  char receive_buffer[ADS_PROTOCOL_MAX_FRAME_BYTES + 1U];
  size_t receive_length;
  uint32_t transmit_sequence;
  uint32_t last_valid_request_ms;
  uint8_t receive_overflow;
  uint8_t has_received_request;
  ADS_ProtocolSafetyState safety_state;
  ADS_AcquireFn acquire;
  ADS_StopFn stop;
  ADS_HeartbeatFn heartbeat;
  ADS_ProtocolTransmitFn transmit;
  ADS_ProtocolTickFn tick;
  void *callback_context;
} ADS_Protocol;

void ADS_Protocol_Init(ADS_Protocol *protocol,
                       ADS_ProtocolTransmitFn transmit,
                       ADS_ProtocolTickFn tick,
                       void *callback_context);
void ADS_Protocol_SetHardwareCallbacks(ADS_Protocol *protocol, ADS_AcquireFn acquire, ADS_StopFn stop);
void ADS_Protocol_SetHeartbeatCallback(ADS_Protocol *protocol, ADS_HeartbeatFn heartbeat);
void ADS_Protocol_ProcessByte(ADS_Protocol *protocol, uint8_t byte);
void ADS_Protocol_Poll(ADS_Protocol *protocol);
ADS_ProtocolSafetyState ADS_Protocol_GetSafetyState(
    const ADS_Protocol *protocol);

#ifdef __cplusplus
}
#endif

#endif /* ADS_PROTOCOL_H */
