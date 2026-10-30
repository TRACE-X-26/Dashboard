#include "ads_protocol.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ADS_DEVICE_ID "STM32-ADS"
#define ADS_FIRMWARE_VERSION "0.2.0-safe-acquisition"

static uint32_t ADS_Protocol_Now(const ADS_Protocol *protocol)
{
  return protocol->tick != NULL ? protocol->tick(protocol->callback_context) : 0U;
}

/* Bounded JSON recognizer. Keys are resolved only in their owning object.
 * Escaped strings are deliberately rejected in this ASCII command subset. */
typedef struct { const char *start, *end; int parent; char kind; } Token;
static Token tokens[64];
static unsigned token_count;
static const char *cursor;
static void whitespace(void) { while (isspace((unsigned char)*cursor)) cursor++; }
static int parse_value(int parent, unsigned depth)
{
  unsigned index;
  char closing;
  if (depth > 8U || token_count >= 64U) return 0;
  whitespace();
  index = token_count++;
  tokens[index] = (Token){cursor, NULL, parent, *cursor};
  if (*cursor == '{' || *cursor == '[')
  {
    closing = *cursor++ == '{' ? '}' : ']';
    whitespace();
    if (*cursor != closing) for (;;)
    {
      if (closing == '}')
      {
        unsigned key = token_count, j;
        if (*cursor != '"' || !parse_value((int)index, depth + 1U)) return 0;
        for (j = index + 1U; j < key; j++)
          if (tokens[j].parent == (int)index && tokens[j].kind == 'K' &&
              tokens[j].end - tokens[j].start == tokens[key].end - tokens[key].start &&
              memcmp(tokens[j].start, tokens[key].start,
                     (size_t)(tokens[key].end - tokens[key].start)) == 0) return 0;
        tokens[key].kind = 'K';
        whitespace(); if (*cursor++ != ':') return 0;
      }
      if (!parse_value((int)index, depth + 1U)) return 0;
      whitespace();
      if (*cursor != ',') break;
      cursor++; whitespace();
    }
    if (*cursor++ != closing) return 0;
  }
  else if (*cursor == '"')
  {
    cursor++;
    while (*cursor && *cursor != '"')
    { if ((unsigned char)*cursor < 32U || *cursor == '\\' || (unsigned char)*cursor > 126U) return 0; cursor++; }
    if (*cursor++ != '"') return 0;
  }
  else if (isdigit((unsigned char)*cursor))
  {
    if (*cursor == '0' && isdigit((unsigned char)cursor[1])) return 0;
    while (isdigit((unsigned char)*cursor)) cursor++;
  }
  else if (strncmp(cursor, "true", 4) == 0) cursor += 4;
  else if (strncmp(cursor, "false", 5) == 0) cursor += 5;
  else if (strncmp(cursor, "null", 4) == 0) cursor += 4;
  else return 0;
  tokens[index].end = cursor;
  return 1;
}
static const char *ADS_Protocol_FindValue(const char *json, const char *key)
{
  unsigned i;
  int parent = 0;
  (void)json;
  if (strcmp(key, "\"command\"") == 0 || strcmp(key, "\"arguments\"") == 0)
    for (i = 1; i + 1U < token_count; i++)
      if (tokens[i].parent == 0 && tokens[i].kind == 'K' &&
          tokens[i].end - tokens[i].start == 9 && memcmp(tokens[i].start, "\"payload\"", 9) == 0)
        { parent = (int)i + 1; break; }
  for (i = 1; i + 1U < token_count; i++)
    if (tokens[i].parent == parent && tokens[i].kind == 'K' &&
        (size_t)(tokens[i].end - tokens[i].start) == strlen(key) &&
        memcmp(tokens[i].start, key, strlen(key)) == 0) return tokens[i + 1U].start;
  return NULL;
}
static int ADS_Protocol_ReadUint32(const char *json, const char *key, uint32_t *value)
{
  const char *p = ADS_Protocol_FindValue(json, key);
  uint32_t n = 0;
  if (!p || !isdigit((unsigned char)*p)) return 0;
  while (isdigit((unsigned char)*p))
  { unsigned d = (unsigned)(*p++ - '0'); if (n > (UINT32_MAX - d) / 10U) return 0; n = n * 10U + d; }
  *value = n; return 1;
}
static int ADS_Protocol_ReadString(const char *json, const char *key, char *value, size_t size)
{
  const char *p = ADS_Protocol_FindValue(json, key), *end;
  size_t n;
  if (!p || *p != '"') return 0;
  end = strchr(++p, '"'); if (!end) return 0;
  n = (size_t)(end - p); if (n >= size) return 0;
  memcpy(value, p, n); value[n] = 0; return 1;
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
      "\"direction\":\"UNCONFIGURED\",\"faults\":%s,"
      "\"hardware_control\":false,\"communication_age_ms\":%lu,"
      "\"heartbeat_timeout_ms\":%u}}}\n",
      (unsigned long)protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to,
      ADS_DEVICE_ID, state, protocol->safety_state == ADS_PROTOCOL_SAFE_IDLE ? "[]" : "[\"COMMUNICATION_TIMEOUT\"]", (unsigned long)age,
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
      "\"GET_FAULTS\",\"READ_MEASUREMENTS\"],\"hardware_control\":false}}}\n",
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

static void ADS_Protocol_SendMeasurements(ADS_Protocol *protocol, uint32_t reply_to)
{
  static const char *names[] = {"voltage", "current", "power", "temperature", "rpm"};
  static const char *units[] = {"V", "A", "W", "degC", "rpm"};
  ADS_Sample samples[5] = {{0}};
  char result[1600];
  size_t used = 0;
  unsigned i;
  if (protocol->acquire != NULL) protocol->acquire(samples, protocol->callback_context);
  used = (size_t)snprintf(result, sizeof(result), "{\"measurements\":{");
  for (i = 0; i < 5; i++)
  {
    char value[40] = "null";
    int valid = samples[i].valid && samples[i].milli_value >= -2000000000 && samples[i].milli_value <= 2000000000;
    /* Fixed-point formatting avoids newlib's optional printf float support. */
    if (valid) {
      int32_t v = samples[i].milli_value;
      unsigned long magnitude = (unsigned long)(v < 0 ? -v : v);
      snprintf(value, sizeof(value), "%s%lu.%03lu", v < 0 ? "-" : "", magnitude / 1000U, magnitude % 1000U);
    }
    used += (size_t)snprintf(result + used, sizeof(result) - used,
      "%s\"%s\":{\"value\":%s,\"unit\":\"%s\",\"valid\":%s,\"timestamp_ms\":%lu}",
      i ? "," : "", names[i], value, units[i], valid ? "true" : "false", (unsigned long)samples[i].timestamp_ms);
  }
  snprintf(result + used, sizeof(result) - used, "}}");
  {
    char frame[2048];
    int written = snprintf(frame, sizeof(frame),
      "{\"version\":1,\"type\":\"measurement\",\"seq\":%lu,\"device_id\":\"%s\",\"timestamp_ms\":%lu,\"payload\":{\"reply_to\":%lu,\"result\":%s}}\n",
      (unsigned long)++protocol->transmit_sequence, ADS_DEVICE_ID,
      (unsigned long)ADS_Protocol_Now(protocol), (unsigned long)reply_to, result);
    if (written > 0 && (size_t)written < sizeof(frame)) ADS_Protocol_Transmit(protocol, frame);
  }
}

void ADS_Protocol_SetHardwareCallbacks(ADS_Protocol *protocol, ADS_AcquireFn acquire, ADS_StopFn stop)
{
  protocol->acquire = acquire;
  protocol->stop = stop;
  if (stop != NULL) stop(protocol->callback_context);
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

  token_count = 0; cursor = frame;
  if (!parse_value(-1, 0U))
  { ADS_Protocol_SendError(protocol, 0, "MALFORMED_FRAME", "Invalid JSON structure"); return; }
  whitespace();
  if (*cursor || tokens[0].kind != '{')
  { ADS_Protocol_SendError(protocol, 0, "MALFORMED_FRAME", "Expected one JSON object"); return; }
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


  ADS_Protocol_Poll(protocol);
  if (strcmp(type, "heartbeat") == 0)
  {
    protocol->last_valid_request_ms = ADS_Protocol_Now(protocol);
    protocol->has_received_request = 1U;
    if (protocol->heartbeat != NULL)
      protocol->heartbeat(protocol->last_valid_request_ms, protocol->callback_context);
    ADS_Protocol_SendAck(
        protocol, request_sequence,
        protocol->safety_state == ADS_PROTOCOL_SAFE_IDLE ?
        "{\"alive\":true,\"state\":\"SAFE_IDLE\",\"hardware_control\":false}" :
        "{\"alive\":true,\"state\":\"COMMUNICATION_TIMEOUT\",\"hardware_control\":false}");
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
  {
    const char *arguments = ADS_Protocol_FindValue(frame, "\"arguments\"");
    if (arguments == NULL || *arguments != '{')
    { ADS_Protocol_SendError(protocol, request_sequence, "MALFORMED_COMMAND", "Arguments must be an object"); return; }
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
                         protocol->safety_state == ADS_PROTOCOL_SAFE_IDLE ?
                         "{\"faults\":[],\"state\":\"SAFE_IDLE\"}" :
                         "{\"faults\":[\"COMMUNICATION_TIMEOUT\"],\"state\":\"COMMUNICATION_TIMEOUT\"}");
  }
  else if (strcmp(command, "READ_MEASUREMENTS") == 0)
  {
    ADS_Protocol_SendMeasurements(protocol, request_sequence);
  }
  else if (ADS_Protocol_IsControlCommand(command))
  {
    /* Stop requests always attempt shutdown, but cannot claim physical success
     * while relay operation is unverified. Never clear a latched timeout. */
    if ((strcmp(command, "STOP_MOTOR") == 0 || strcmp(command, "STOP_TEST") == 0) && protocol->stop != NULL)
      protocol->stop(protocol->callback_context);
    ADS_Protocol_SendError(protocol, request_sequence, "CONTROL_DISABLED",
                           "Motor outputs are disabled pending verification");
  }
  else
  {
    ADS_Protocol_SendError(protocol, request_sequence, "UNSUPPORTED_COMMAND",
                           "Command is not supported by this firmware");
  }
}

void ADS_Protocol_SetHeartbeatCallback(ADS_Protocol *protocol, ADS_HeartbeatFn heartbeat)
{
  if (protocol != NULL) protocol->heartbeat = heartbeat;
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
  if (byte == 0U) { protocol->receive_overflow = 1U; return; }
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
  if (protocol == NULL)
  {
    return;
  }
  if ((uint32_t)(ADS_Protocol_Now(protocol) -
                 protocol->last_valid_request_ms) >=
      ADS_PROTOCOL_HEARTBEAT_TIMEOUT_MS)
  {
    protocol->safety_state = ADS_PROTOCOL_COMMUNICATION_TIMEOUT;
    if (protocol->stop != NULL) protocol->stop(protocol->callback_context);
  }
}

ADS_ProtocolSafetyState ADS_Protocol_GetSafetyState(
    const ADS_Protocol *protocol)
{
  return protocol == NULL ? ADS_PROTOCOL_COMMUNICATION_TIMEOUT
                          : protocol->safety_state;
}
