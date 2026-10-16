#include "ads_protocol.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ADS_DEVICE_ID "STM32-ADS"
#define ADS_FIRMWARE_VERSION "0.1.0-communication-only"

static uint32_t ADS_Protocol_Now(const ADS_Protocol *protocol)
{
  return protocol->tick != NULL ? protocol->tick(protocol->callback_context) : 0U;
}

static const char *ADS_Protocol_FindValue(const char *json, const char *key)
{
  const char *position = json;
  const size_t key_length = strlen(key);

  while ((position = strstr(position, key)) != NULL)
  {
    position += key_length;
    while ((*position != '\0') && isspace((unsigned char)*position))
    {
      position++;
    }
    if (*position == ':')
    {
      position++;
      while ((*position != '\0') && isspace((unsigned char)*position))
      {
        position++;
      }
      return position;
    }
  }
  return NULL;
}

static int ADS_Protocol_ReadUint32(const char *json, const char *key,
                                   uint32_t *value)
{
  const char *position = ADS_Protocol_FindValue(json, key);
  char *end = NULL;
  unsigned long parsed;

  if ((position == NULL) || !isdigit((unsigned char)*position))
  {
    return 0;
  }
  parsed = strtoul(position, &end, 10);
  if ((end == position) || (parsed > 0xFFFFFFFFUL))
  {
    return 0;
  }
  *value = (uint32_t)parsed;
  return 1;
}

static int ADS_Protocol_ReadString(const char *json, const char *key,
                                   char *value, size_t value_size)
{
  const char *position = ADS_Protocol_FindValue(json, key);
  const char *end;
  size_t length;

  if ((position == NULL) || (*position != '"') || (value_size == 0U))
  {
    return 0;
  }
  position++;
  end = strchr(position, '"');
  if (end == NULL)
  {
    return 0;
  }
  length = (size_t)(end - position);
  if (length >= value_size)
  {
    return 0;
  }
  memcpy(value, position, length);
  value[length] = '\0';
  return 1;
}

static void ADS_Protocol_Transmit(ADS_Protocol *protocol, const char *frame)
{
  if ((protocol->transmit != NULL) && (frame != NULL))
  {
    (void)protocol->transmit((const uint8_t *)frame, strlen(frame),
                             protocol->callback_context);
  }
}

static void ADS_Protocol_SendError(ADS_Protocol *protocol, uint32_t reply_to,
                                   const char *code, const char *message)
{
  char frame[512];
  int written;

  protocol->transmit_sequence++;
  written = snprintf(
      frame, sizeof(frame),
      "{\"version\":1,\"type\":\"error\",\"seq\":%lu,"
      "\"device_id\":\"%s\",\"timestamp_ms\":%lu,\"payload\":{"
      "\"reply_to\":%lu,\"code\":\"%s\",\"message\":\"%s\"}}\n",
      (unsigned long)protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to,
      code, message);
  if ((written > 0) && ((size_t)written < sizeof(frame)))
  {
    ADS_Protocol_Transmit(protocol, frame);
  }
}

static void ADS_Protocol_SendStatus(ADS_Protocol *protocol, uint32_t reply_to)
{
  char frame[640];
  const char *state = protocol->safety_state == ADS_PROTOCOL_SAFE_IDLE
                          ? "SAFE_IDLE"
                          : "COMMUNICATION_TIMEOUT";
  uint32_t age = protocol->has_received_request
                     ? ADS_Protocol_Now(protocol) - protocol->last_valid_request_ms
                     : 0U;
  int written;

  protocol->transmit_sequence++;
  written = snprintf(
      frame, sizeof(frame),
      "{\"version\":1,\"type\":\"status\",\"seq\":%lu,"
      "\"device_id\":\"%s\",\"timestamp_ms\":%lu,\"payload\":{"
      "\"reply_to\":%lu,\"result\":{\"device_id\":\"%s\","
      "\"state\":\"%s\",\"pwm_percent\":0,"
      "\"direction\":\"UNCONFIGURED\",\"faults\":[],"
      "\"hardware_control\":false,\"communication_age_ms\":%lu,"
      "\"heartbeat_timeout_ms\":%u}}}\n",
      (unsigned long)protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to,
      ADS_DEVICE_ID, state, (unsigned long)age,
      ADS_PROTOCOL_HEARTBEAT_TIMEOUT_MS);
  if ((written > 0) && ((size_t)written < sizeof(frame)))
  {
    ADS_Protocol_Transmit(protocol, frame);
  }
}

static void ADS_Protocol_SendCapabilities(ADS_Protocol *protocol,
                                          uint32_t reply_to)
{
  char frame[640];
  int written;

  protocol->transmit_sequence++;
  written = snprintf(
      frame, sizeof(frame),
      "{\"version\":1,\"type\":\"capabilities\",\"seq\":%lu,"
      "\"device_id\":\"%s\",\"timestamp_ms\":%lu,\"payload\":{"
      "\"reply_to\":%lu,\"result\":{\"device_id\":\"%s\","
      "\"firmware_version\":\"%s\",\"measurement_types\":[],"
      "\"commands\":[\"GET_STATUS\",\"GET_CAPABILITIES\","
      "\"GET_FAULTS\"],\"hardware_control\":false}}}\n",
      (unsigned long)protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to,
      ADS_DEVICE_ID, ADS_FIRMWARE_VERSION);
  if ((written > 0) && ((size_t)written < sizeof(frame)))
  {
    ADS_Protocol_Transmit(protocol, frame);
  }
}

static void ADS_Protocol_SendAck(ADS_Protocol *protocol, uint32_t reply_to,
                                 const char *result)
{
  char frame[512];
  int written;

  protocol->transmit_sequence++;
  written = snprintf(
      frame, sizeof(frame),
      "{\"version\":1,\"type\":\"ack\",\"seq\":%lu,"
      "\"device_id\":\"%s\",\"timestamp_ms\":%lu,\"payload\":{"
      "\"reply_to\":%lu,\"result\":%s}}\n",
      (unsigned long)protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to,
      result);
  if ((written > 0) && ((size_t)written < sizeof(frame)))
  {
    ADS_Protocol_Transmit(protocol, frame);
  }
}

static int ADS_Protocol_IsControlCommand(const char *command)
{
  return (strcmp(command, "START_TEST") == 0) ||
         (strcmp(command, "STOP_TEST") == 0) ||
         (strcmp(command, "SET_PWM") == 0) ||
         (strcmp(command, "SET_DIRECTION") == 0) ||
         (strcmp(command, "STOP_MOTOR") == 0);
}

static void ADS_Protocol_HandleFrame(ADS_Protocol *protocol, const char *frame)
{
  uint32_t version = 0U;
  uint32_t request_sequence = 0U;
  char type[24];
  char device_id[40];
  char command[32];
  const char *timestamp_value;
  const char *payload_value;

  timestamp_value = ADS_Protocol_FindValue(frame, "\"timestamp_ms\"");
  payload_value = ADS_Protocol_FindValue(frame, "\"payload\"");

  if (!ADS_Protocol_ReadUint32(frame, "\"version\"", &version) ||
      !ADS_Protocol_ReadUint32(frame, "\"seq\"", &request_sequence) ||
      !ADS_Protocol_ReadString(frame, "\"type\"", type, sizeof(type)) ||
      !ADS_Protocol_ReadString(frame, "\"device_id\"", device_id,
                              sizeof(device_id)) ||
      (device_id[0] == '\0') || (timestamp_value == NULL) ||
      !isdigit((unsigned char)*timestamp_value) || (payload_value == NULL) ||
      (*payload_value != '{'))
  {
    ADS_Protocol_SendError(protocol, request_sequence, "MALFORMED_FRAME",
                           "Required protocol fields are missing or invalid");
    return;
  }
  if (version != ADS_PROTOCOL_VERSION)
  {
    ADS_Protocol_SendError(protocol, request_sequence, "UNSUPPORTED_VERSION",
                           "Only protocol version 1 is supported");
    return;
  }

  protocol->last_valid_request_ms = ADS_Protocol_Now(protocol);
  protocol->has_received_request = 1U;
  protocol->safety_state = ADS_PROTOCOL_SAFE_IDLE;

  if (strcmp(type, "heartbeat") == 0)
  {
    ADS_Protocol_SendAck(
        protocol, request_sequence,
        "{\"alive\":true,\"state\":\"SAFE_IDLE\",\"hardware_control\":false}");
    return;
  }
  if (strcmp(type, "command") != 0)
  {
    ADS_Protocol_SendError(protocol, request_sequence,
                           "UNSUPPORTED_MESSAGE_TYPE",
                           "Firmware accepts command and heartbeat requests");
    return;
  }
  if (!ADS_Protocol_ReadString(frame, "\"command\"", command,
                               sizeof(command)))
  {
    ADS_Protocol_SendError(protocol, request_sequence, "MALFORMED_COMMAND",
                           "Command name is missing or invalid");
    return;
  }
  if (strcmp(command, "GET_STATUS") == 0)
  {
    ADS_Protocol_SendStatus(protocol, request_sequence);
  }
  else if (strcmp(command, "GET_CAPABILITIES") == 0)
  {
    ADS_Protocol_SendCapabilities(protocol, request_sequence);
  }
  else if (strcmp(command, "GET_FAULTS") == 0)
  {
    ADS_Protocol_SendAck(protocol, request_sequence,
                         "{\"faults\":[],\"state\":\"SAFE_IDLE\"}");
  }
  else if (strcmp(command, "READ_MEASUREMENTS") == 0)
  {
    ADS_Protocol_SendError(protocol, request_sequence,
                           "MEASUREMENTS_UNAVAILABLE",
                           "ADC and sensor acquisition are not configured");
  }
  else if (ADS_Protocol_IsControlCommand(command))
  {
    ADS_Protocol_SendError(protocol, request_sequence, "CONTROL_DISABLED",
                           "Motor outputs are disabled pending verification");
  }
  else
  {
    ADS_Protocol_SendError(protocol, request_sequence, "UNSUPPORTED_COMMAND",
                           "Command is not supported by this firmware");
  }
}

void ADS_Protocol_Init(ADS_Protocol *protocol,
                       ADS_ProtocolTransmitFn transmit,
                       ADS_ProtocolTickFn tick,
                       void *callback_context)
{
  if (protocol == NULL)
  {
    return;
  }
  memset(protocol, 0, sizeof(*protocol));
  protocol->transmit = transmit;
  protocol->tick = tick;
  protocol->callback_context = callback_context;
  protocol->last_valid_request_ms = ADS_Protocol_Now(protocol);
  protocol->safety_state = ADS_PROTOCOL_SAFE_IDLE;
}

void ADS_Protocol_ProcessByte(ADS_Protocol *protocol, uint8_t byte)
{
  if (protocol == NULL)
  {
    return;
  }
  if (byte == '\r')
  {
    return;
  }
  if (byte == '\n')
  {
    if (protocol->receive_overflow != 0U)
    {
      ADS_Protocol_SendError(protocol, 0U, "FRAME_TOO_LARGE",
                             "Frame exceeds firmware receive limit");
    }
    else if (protocol->receive_length > 0U)
    {
      protocol->receive_buffer[protocol->receive_length] = '\0';
      ADS_Protocol_HandleFrame(protocol, protocol->receive_buffer);
    }
    protocol->receive_length = 0U;
    protocol->receive_overflow = 0U;
    return;
  }
  if (protocol->receive_overflow != 0U)
  {
    return;
  }
  if (protocol->receive_length >= ADS_PROTOCOL_MAX_FRAME_BYTES)
  {
    protocol->receive_overflow = 1U;
    return;
  }
  protocol->receive_buffer[protocol->receive_length++] = (char)byte;
}

void ADS_Protocol_Poll(ADS_Protocol *protocol)
{
  if ((protocol == NULL) || (protocol->has_received_request == 0U))
  {
    return;
  }
  if ((uint32_t)(ADS_Protocol_Now(protocol) -
                 protocol->last_valid_request_ms) >
      ADS_PROTOCOL_HEARTBEAT_TIMEOUT_MS)
  {
    protocol->safety_state = ADS_PROTOCOL_COMMUNICATION_TIMEOUT;
  }
}

ADS_ProtocolSafetyState ADS_Protocol_GetSafetyState(
    const ADS_Protocol *protocol)
{
  return protocol == NULL ? ADS_PROTOCOL_COMMUNICATION_TIMEOUT
                          : protocol->safety_state;
}
