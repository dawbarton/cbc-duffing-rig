# CBC Duffing Rig todo

## Current

Differential DAC drive implemented in `cbc-rig` (helic-daq commit `813170f`),
flashed and verified with exciter/laser power off. Awaiting David:
- [ ] Electrical check on a scope that A - C is bipolar and non-inverting
      before powering the exciter (software cannot verify DAC pin voltages).
- [ ] First energised test: 0.1 V pp (amplitude 0.05 V) sine near 5-10 Hz,
      watch laser displacement, reconfigure to safe state on any instability.

## Future

- Consider updating the host Python simulator/tests to model the differential
  A/C mapping (currently model the old single-ended `rig_out_channel`).
- Feedback-control safety before closed-loop CBC: firmware amplitude ceiling,
  output arming/lease + comms-loss quieting, ADC-fault quieting, applied-output
  telemetry. These touch shared `rt_loop`/drivers, so agree scope with David.
