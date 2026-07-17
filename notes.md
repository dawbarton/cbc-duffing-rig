# CBC Duffing Rig incremental notes

## 2026-07-17T17:04+00:00 Initial repository setup and firmware-review plan

- David confirmed that DAC A is the positive differential current-controller input and DAC C is the negative input; DAC B is broken. `AGENTS.md` was corrected before project-repository initialization.
- The actuator power supply is currently off. Online DAQ checks are permitted, but the actuator cannot produce excitation in this state.
- The project-level Git repository and prescribed folder structure were initialized for first use.
- `helic-daq` is an independent Git repository at `/workspace/helic-daq`, exposed here through the `/workspace/cbc-duffing-rig/helic-daq` symlink.
- Agreed review sequence: establish project context; inventory `cbc-rig`; assess safety-critical output behavior; check host/protocol compatibility; build and perform safe offline/online checks; document recommendations.
- The workflow pauses for confirmation after each completed step.

## 2026-07-17T17:10+00:00 `cbc-rig` firmware inventory

- Reviewed independent `helic-daq` repository commit `f9a7354`; its worktree was clean and matched `origin/main` at the start of the review.
- CBC is the `fw-cbc-rig` crate under `firmware/experiments/cbc-rig`, not a top-level crate. It defaults to a W5500, static address `192.168.1.235`, 8 kHz hardware-timed sampling, and the compile-time `PassThrough` controller.
- `board.rs` assigns SPI1 analogue hardware, AD7609 CONVST/BUSY, UART laser, and GP14 timing output consistently with repository documentation. The four AD5064 channels are configured as unipolar.
- Firmware currently selects DAC channel A (`OUTPUT_CHANNEL = 0`), zeros every DAC channel during initialisation, and subsequently writes the logical `out` value directly to A. No code establishes the corrected approximately 2 V reference on DAC C.
- This mismatch is a static-code finding. The exact safe common-mode/offset mapping still needs to be established before proposing an implementation; the actuator must remain unpowered meanwhile.

## 2026-07-17T17:13+00:00 Static safety review

- Established: logical `out` is the unconstrained sum of target/controller, forcing, and table terms. Host writes reject non-finite values, but there is no rig-specific amplitude bound; the unipolar DAC driver merely clamps the final A-channel request into 0–4.096 V.
- Established: the streamed `out` value is recorded before DAC clamping, so it can disagree with the actual voltage. This would invalidate excitation-amplitude records when negative or excessive requests occur.
- Established: writable `rig_out_channel` accepts all indices 0–3. It can therefore select broken channel B or overwrite the required channel-C reference. The physical CBC output mapping should not be freely redirectable.
- Established: a TCP disconnect stops UDP streaming only. Target, forcing, table playback, controller state, and DAC actuation continue indefinitely. The firmware has no output arming lease or communication-loss quieting.
- Established: an ADC BUSY timeout increments `tick_timeouts` but still executes measurement, control, and actuation using the last/decoded values. This is unsafe for future feedback control. The core-0 time watchdog protects Embassy timer progress, not actuator output.
- Established: startup attempts to write 0 V to all DACs; failure emits a warning but the sample clock and actuation still start. There is no displacement/current trip, output-enable interlock, or MCU-failure mechanism capable of clearing the DAC's retained last value.
- Required before actuator power-on: define and implement fixed differential A/C behavior (likely both at a common-mode near 2.048 V for logical zero, with A offset by the signed command), prevent selection of B/C as the driven output, and verify the mapping electrically against the current-controller input specification.
- Required before actuator power-on: impose the stated 2 V peak-to-peak differential ceiling (a symmetric logical limit would be ±1 V), make output default-disabled with an explicit arming/lease mechanism, quiet it on control loss and acquisition faults, and expose the actually applied logical output in telemetry. Initial energised tests should use ±0.05 V peak (0.1 V peak-to-peak).
- Recommended: add configurable displacement and current trips after establishing trustworthy sensor scaling, and use a hardware output-enable/interlock if safe shutdown must survive MCU halt or loss of firmware control.
- Unknown: whether 2.000 V or exact half-scale 2.048 V is the intended current-controller common-mode, and whether any sign/gain inversion exists between DAC pins and controller differential input. Confirm before implementation rather than inferring from the DAC reference alone.

## 2026-07-17T17:16+00:00 Host compatibility review

- Established: both host APIs connect by reading `Status`, then discover parameter and source tables by name; they do not require fixed source IDs or parameter indices for ordinary get/set/capture workflows.
- Established: protocol v2 already permits experiment-specific parameters/sources, so replacing or removing CBC-specific `rig_out_channel` can be compatible if host code continues using discovered names.
- Established: the Python simulator and its tests currently model `rig_out_channel` as any integer DAC index 0-3 and stream logical `out = target + forcing + table`, matching the unsafe single-ended firmware semantics.
- Established: the CLI `sine`, `upload`, and `capture` commands do not enforce the Duffing rig's 0.1 Vpp starting point or 2 Vpp limit; they rely on firmware/device-side acceptance.
- Recommendation: update simulator, protocol docs, and host tests with any firmware change so local development reflects the differential DAC A/C mapping, the applied-output telemetry, and the restricted safe command range.

## 2026-07-17T17:20+00:00 Offline and live DAQ verification

- Offline checks passed: Rust root `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, and `cargo test`; firmware `cargo fmt --all -- --check`, release clippy, release workspace build, `tools/check_rt_layout.py`, W6100 CBC build, and W6100 whirl build; Python host tests via `uv run --python 3.12`; Julia host tests.
- MATLAB host tests were not run because `matlab` is not installed in this environment.
- Live read-only DAQ checks, with no flashing and no actuator-output commands, discovered `cbc-rig` firmware `0.1.0 f9a7354` at `192.168.1.235`; status reported protocol v2, 39 params, 14 sources, 8 kHz, no overruns, no tick timeouts, and no laser parser/UART/sync errors.
- Selected live parameters: `rig_out_channel = 0.0`, `freq = 0.0`, `table_len = 0`, `table_mode = 0`, `laser ~= 24.819 mm`, `loop_time_max = 34 us`.
- One short decimated stream capture of `adc0,laser,out,cmd_epoch` recorded 1000 records with no UDP loss. `out` and `cmd_epoch` stayed exactly zero; `adc0` mean was about 0.491 V with 5 mV peak-to-peak; laser peak-to-peak was about 0.0023 mm.
- Report written to `/workspace/cbc-duffing-rig/reports/2026-07-17-cbc-rig-review/report.md`; raw capture and plot stored at `/workspace/cbc-duffing-rig/data/2026-07-17-daq-readonly-capture.npz` and `/workspace/cbc-duffing-rig/results/2026-07-17-daq-readonly-capture.png`.
