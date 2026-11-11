# Motor protection configuration — November 11, 2026

Subsequent operator confirmation also enabled the separate supervised operator
profile. See [current build instructions](SUPERVISED_OPERATOR_BUILD.md).
Statements below about remaining disabled gates describe the earlier cutoff-only
update; the generic disabled example still retains those gates.

Current cutoff: **1.5 A** (1500 mA). Supply acceptance window: **11.0–13.0 V**.
Current at or above the cutoff fails readiness; voltage outside the window fails
readiness. Existing fault shutdown uses motor INA219 readings only.

The operator explicitly reported these limits verified in this conversation on
2026-11-11. Accordingly, firmware and both Pi example profiles now set the
protection-limits verification flag. This records operator confirmation, not an
independent bench check by the coding agent or a manufacturer rating.

The proposed current setting was selected above the historical maximum logged
reading of 1.133 A. Those approximately one-second recordings do not establish
instantaneous startup peaks, allowable sustained current, or safe stall duration.
No new startup grace period or overload delay has been introduced.

This supersedes the earlier provisional 2.5 A setting and its unverified flag.
Other approvals remain independent: relay reset behavior, physical cutoff,
communication-loss shutdown, measurement calibration and supervised-mode
approval are unchanged. Physical output permission remains disabled; these
changes alone do not authorize a motor start. No hardware was flashed or run.
