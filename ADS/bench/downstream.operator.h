#ifndef ADS_DOWNSTREAM_OPERATOR_H
#define ADS_DOWNSTREAM_OPERATOR_H
/* Explicit operator-selected motor-enabled build, separate from the disabled
 * default. Reuses the operator's existing relay/cutoff/measurement attestations.
 * The operator specified 10-14 V, 1.5 A, 50% PWM and a 30-second maximum.
 * These are operator acceptance records, not independent physical verification
 * by the coding agent. Live protection and downstream power checks stay active. */
#include "supervised.operator.h"
#define ADS_PROTECTION_LIMITS_VERIFIED 1
#define ADS_MOTOR_MIN_VOLTAGE_MV 10000U
#define ADS_MOTOR_MAX_VOLTAGE_MV 14000U
#define ADS_MOTOR_MAX_CURRENT_MA 1500U
#endif
