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

## 2026-07-17T22:46+00:00 Differential DAC drive implemented and flashed

- Implemented the AGENTS.md differential drive scheme in `cbc-rig` (helic-daq commit `813170f`), replacing the previous single-ended output. Changes in `firmware/experiments/cbc-rig/src/rig.rs` only:
  - Added `MID_RAIL = DAC_VREF/2 = 2.048 V` and `NEG_REF_CHANNEL = 2` (channel C).
  - `init()`: after `zero_all`, hold C at `MID_RAIL` and park A at `MID_RAIL` so the differential rest state (A - C) is zero, avoiding a one-tick full-scale negative kick between init and the first `actuate`.
  - `actuate()`: write `MID_RAIL + out` (no sign inversion). Streamed `out` remains the signed differential command; DAC driver still clamps to 0-4.096 V.
  - `normalise_param`: lock `rig_out_channel` to channel A (0); reject broken B (1) and the C reference (2).
- David's decisions (via question prompt): common-mode 2.048 V exact half-scale; no sign/gain inversion (A up = more drive); 2 V pp remains a soft/host limit (no firmware clamp for now).
- Offline verification passed: `cargo fmt --check`, release clippy `-D warnings` and release build for both W5500 (default) and W6100, and `tools/check_rt_layout.py` (hot symbols `measure`/`actuate` still in SRAM).
- Live verification with exciter and laser power OFF: flashed via `probe-rs`/`cargo run`; clean boot, network up at 192.168.1.235, RT loop 8 kHz with no overruns/tick-timeouts and no "DAC common-mode setup failed" warning (both init writes succeeded). `rig_out_channel` set to 1 and 2 both rejected ("bad value"); 0 accepted. A 0.05 V pp logical sine (amplitude 0.025 V, 2 Hz) streamed back symmetric about zero (out min/max ±0.025, mean 0.0000); adc0 quiescent (~0.38 V, no current, power off); laser 0 (power off); no UDP loss. Forcing then zeroed; device left quiescent on committed build `813170f`.
- Note: `probe-rs download` + `probe-rs reset` left the core in a non-serving state; `cargo run` (`probe-rs run`) flashed and reset cleanly. Use the cargo runner for flashing.
- OUTSTANDING before powering the exciter: David to confirm electrically (scope) that A - C is bipolar and non-inverting against the current-controller input. Software cannot verify DAC pin voltages. Capture saved at `shared`-free scratch only (not retained).

## 2026-07-17T22:46+00:00 DAC startup timing fix, monitoring note, quick-start

- Reviewing the DAC startup: the AD5064 requires ~3 us between sequential SPI words (driver timing note in `helic-drivers/src/ad5064.rs`; `zero_all_with_delay` spaces its writes by 3 us). The previous commit's back-to-back `write_volts` calls for the C/A common-mode setup (and the missing gap after zeroing) violated this. Fixed in helic-daq `ba8748c` by adding `CbcRig::write_dac_channels_spaced`, a startup-only spaced multi-write helper (mirrors `zero_all_with_delay` for arbitrary setpoints) using `embassy_time::block_for(3 us)` before each word. Verified: offline checks pass; on hardware the device boots with no DAC warning and diagnostics are clean after `diag_reset` (overruns/clock_jitter/tick_timeouts/cmd_backlog_max = 0, loop_time_max 35 us).
- A driver-level `write_all_with_delay` helper would be the cleaner home for this, but `helic-drivers` is shared code that AGENTS.md says not to modify; implemented locally in `cbc-rig` instead. Offer to move it into the driver if David approves.
- Added a `## Health Monitoring` section to the project `AGENTS.md`: routinely check `overruns`, `tick_timeouts`, `clock_jitter`, loop/wake timing maxima, `cmd_backlog_max`, `records_dropped`, and the `laser_*` error counters for anomalies (after flashing, around captures, during long runs); reset trackers with `diag_reset`. Baselines cross-referenced to `helic-daq/notes.md`. Exact param names taken from `helic-daq get`.
- Populated the previously empty `quick-start.md` with connection, build/flash (incl. the `probe-rs download`+`reset` gotcha), differential-drive semantics, physical-state caveats, and idle sanity numbers.

## 2026-07-17T22:46+00:00 Moved DAC spacing helper into the AD5064 driver

- Per David, moved the spaced multi-write from `cbc-rig` into its natural home on the shared AD5064 driver (helic-daq `6f82ffc`); this supersedes the local `write_dac_channels_spaced` from `ba8748c`.
- `helic-drivers/src/ad5064.rs`: added `WORD_SETTLE_US = 3` (used by `zero_all_with_delay`) and `write_volts_with_delay(setpoints, delay)`; documented on `write_code`/`write_volts` that they are single unspaced words needing the inter-word delay when called back-to-back (pointing to the batch helpers), so future agents spot the requirement; expanded the module timing note; added a spacing unit test.
- `cbc-rig` `init()` now defines all four channels in one spaced pass via the driver method: C and A at the common-mode reference (C first so A settles last), B and D at 0 V. Removed the local helper and its constant.
- Verified: root fmt/clippy/`cargo test -p helic-drivers` (incl. new `write_volts_with_delay_spaces_between_words_only`), firmware fmt/clippy/build for W5500+W6100, RT-layout. On hardware (exciter/laser off) `6f82ffc` boots with no DAC warning; after `diag_reset` overruns/tick_timeouts/cmd_backlog_max = 0, clock_jitter 1 us (documented baseline), loop_time_max 35 us; `rig_out_channel` still rejects B/C; a 0.05 V pp logical sine streams symmetric about zero with no loss; left quiescent.

## 2026-07-17T22:46+00:00 Split firmware detail into docs/firmware-guide.md

- Per David's steer that the firmware should stay largely fixed while experiments run, moved the firmware technical detail out of `quick-start.md` into a new `docs/firmware-guide.md` (build/flash/verify, differential DAC drive, AD5064 timing, compile-time config, known gaps).
- Rewrote `quick-start.md` to focus on running experiments over the host API: CLI commands, the Fourier-series/table excitation model, capturable sources, safe operating points, health check, physical-state caveats, sanity numbers.
- Added a pointer from `AGENTS.md` to `docs/firmware-guide.md` and clarified quick-start vs guide roles.

## 2026-07-18T09:50+00:00 Literature review and method docs in docs/methods/

- Reviewed the experimental-continuation literature, anchored on the Kerschen review (Raze, Abeloos, Kerschen 2024, arXiv:2408.00138) plus Barton's CBC/stability work (arXiv:1506.04052), the coupled-modes beam (arXiv:1808.01865), adaptive-filtering CBC (Abeloos et al. 2021; arXiv:2203.10306), PLL/phase-resonance (Peeters 2011, Denis 2018, NCPLL 2025), CBC-vs-PLL consistency (Abeloos 2022), GP-regression continuation (Renson/Barton/Neild 2019), and derivative-free arclength CBC (arXiv:2408.00138, theory arXiv:2505.02262).
- Wrote six implementation-oriented method docs for future agents in `docs/methods/` (each with a rig-specific `## Duffing rig` section at the end): CBC, PLL, stability/bifurcation estimation (ARX/Floquet), adaptive-filtering (stepped/swept) CBC, derivative-free arclength CBC, GP-regression continuation. Added a `## Methods` section to `AGENTS.md` linking all six.
- Docs are written as agent implementation guidance (technical, high-signal), not general-reader explainers, per David's steer.
- Caveat recorded in the docs: some bibliographic details (years/venues) are from memory and paraphrased paper fetches; the arXiv IDs above were verified via search, other citations should be confirmed before formal use. The lightweight fetch summaries of PLL/adaptive-filter equations were cartoons and were rewritten against established formulations.
- Recurring theme across all docs: every method closes the loop through the exciter, so the firmware safety envelope (amplitude ceiling, output arming/lease, comms-loss + ADC-fault quieting, applied-output telemetry, per-evaluation trip to safe state) is a prerequisite for any energised closed-loop run — ties directly to the todo.md Future items.

## 2026-07-18T10:16+00:00 Firmware-change review against docs/methods/

Reviewed all six method docs against the `cbc-rig` firmware (rt_loop.rs, params.rs,
generator.rs, table.rs, controller.rs, pid.rs) to decide what firmware work is needed.

- **Finding:** firmware is already a generic phase-coherent excitation + streaming engine;
  algorithmic logic belongs host-side. Runtime-configurable over TCP with no reflash:
  `freq` (→SetIncrement, shared by target+forcing), `target` Fourier coeffs (H≤16), `forcing`
  Fourier coeffs (feed-forward added to output), arbitrary `table` upload (set_block/commit,
  ≤4096 samples, own phase accumulator/gain/mode/mult/phase/trigger), ctrl/rig params, diag_reset.
  Streams adc0-7, laser, ctrl telemetry, target, forcing, table, out, cmd_epoch per tick.
  Signal chain: `out = controller.tick(inputs,target,dt) + forcing + table`.
- **Essential change 1 (functional):** select a stabilising controller — the documented
  compile-time swap `ActiveController = PassThrough → PidController` in config.rs. PID acts on
  `error = target - inputs[feedback]` = CBC law `u=K(r-x)`; filtered derivative (tau_d) present.
  Run as PD (ki=0) so integral doesn't fight A0/mean; non-invasiveness holds (e→0 ⇒ control→0
  at controlled harmonics regardless of gain). Existing PidController is adequate.
- **Essential change 2 (safe closed-loop):** firmware-level safety hard-constraints, listed as
  prerequisites in every closed-loop doc + firmware-guide "Known gaps": (1) output amplitude
  ceiling on final `out` (none today — DAC only silently saturates at ±2.048V); (2) displacement
  trip on `laser`; (3) stale-laser/ADC-fault quieting; (4) comms-loss/heartbeat quieting
  (esp. for continuously-adapting loops); (5) output arming/lease. Items 1,3,4 touch shared
  rt_loop/common code → agree scope before implementing (recommend a thin parameterised per-tick
  safety stage in the shared loop).
- **No firmware change needed** for PLL, LTP-ARX/Floquet stability (multisine via table player),
  adaptive-filtering CBC, derivative-free arclength CBC, GP continuation — all host-side (Julia),
  reuse existing excitation/streaming. HARMONICS=16 already exceeds the H≈3 the docs ask for.
- **Keep host-side:** harmonic projection, LMS/RLS, PLL loop, Newton/Broyden/DF corrector, GP.
  Future (latency-driven): in-firmware adaptive canceller would need drive phase θ passed into
  Controller::tick — a shared-trait change to scope separately.
- Recommended order: (1) PID swap + open-loop→low-gain closed-loop bring-up on stable branch;
  (2) design/review shared safety stage before energised closed-loop; (3) rest host-side.

## 2026-07-18T10:16+00:00 Shared safety-stage design proposal

Wrote `docs/firmware-safety-stage-design.md` — scoped design for the firmware safety
hard-constraints (prerequisite for energised closed-loop CBC/PLL/etc).

- **Architecture:** a generic "safety gate" in shared `rt_loop::run_rt_tick`, run after the
  controller+forcing+table sum and before `rig.actuate`. Opt-in via new trait const
  `Rig::SAFETY_GATED` (default false → compiled out → whirl/pico2w byte-identical). Streamed
  `out` becomes the APPLIED (post-gate) value = applied-output telemetry the docs want.
- **Mechanism (shared, generic):** arm/lease via absolute-deadline atomic `LEASE_DEADLINE_US`
  (wrap-safe vs now_us()); unifies arming, host-crash, comms-loss, off-after-flash into one
  per-tick compare. Latching `SAFETY_TRIPPED`. Clamp/quiet tick counters as diagnostics.
- **Policy (cbc-rig, via 3 defaulted trait hooks):** `clamp_output` = hard ±OUT_CEILING_V;
  `safe_output` = 0.0 (→MID_RAIL zero drive); `output_fault` = laser displacement bound OR
  laser-frame staleness (blind-feedback guard).
- **Host interface, NO protocol change:** new writable base param `arm_lease_ms` applied
  directly on core 0 (like diag_reset) — >0 arms+renews+clears trip, 0 disarms; heartbeat
  renewal holds output live. TCP disconnect cleanup in control_run also expires the lease
  (immediate comms-loss quiet). Read-only safety telemetry (armed/tripped/clamp/quiet) +
  status line.
- **Staging:** (1) trait hooks+gate scaffolding, SAFETY_GATED=false everywhere, no behaviour
  change; (2) ceiling+arm/lease+comms-loss (laser-independent) — the core interlock, verify
  on rig at low ceiling BEFORE any energised closed-loop; (3) displacement/stale trip (needs
  laser sign/calibration commissioning item first); (4) optional adc0 current trip / slew.
- **Out of scope:** in-fw projection/adaptive/PLL, hardware interlock (recommended separate
  track), rate limiting.
- **Open decisions for David (D1-D4):** arm policy (lease vs connection-open); OUT_CEILING_V
  value (from exciter safe input range); displacement bound (pending laser cal); telemetry
  placement (BASE_PARAMS vs cbc extras). Recommendations given in doc.

## 2026-07-18T10:16+00:00 Safety-stage decision D1 resolved

- David chose arm policy = **explicit `arm` flag, no lease/heartbeat** (rationale: operator
  present with emergency power-off, so hung-but-connected host need not auto-quiet).
- Design doc updated: `SAFETY_ARMED` atomic replaces the lease deadline; writable base param
  `arm` (1=arm+clear-trip-if-clear, 0=disarm), applied directly on core 0; TCP disconnect
  still auto-disarms; disarmed after flash. Heartbeat/lease noted as the single future
  extension point if unattended running is ever wanted.
- Remaining open decisions: D2 OUT_CEILING_V (from exciter safe input range), D3 displacement
  bound (pending laser cal), D4 telemetry placement (recommend BASE_PARAMS).

## 2026-07-18T10:16+00:00 Safety stage implemented, flashed, verified

- Implemented the full firmware safety stage per the design doc; flashed to the live rig
  (helic-daq commit `c8c3abe`) with exciter+laser powered off (safe).
- Decisions applied: D2 DAC output window 0.096–4.0 V (4 V ceiling per David; floor
  symmetric about MID_RAIL for the interim unipolar board; future bipolar board → independent
  ± limits). D3 displacement window 10–40 mm (rest ≈25 mm). D4 telemetry in BASE_PARAMS.
- Two host params (not four, to fit the 1023/1024-byte discovery budget): writable `arm`,
  read-only `safety` bitfield (armed/tripped/clamped/quieted). `MAX_RIG_PARAMS` trimmed 8→6.
- Verified: 51 host tests incl. new `helic-core::safety` (clamp + StaleCounter), root+firmware
  clippy, both board features build for all 3 experiments, RT-layout (gate/hooks in SRAM), fmt.
  On-rig: disarmed-after-flash, blind-laser trip+quiet (`safety=0b1010`), arm/disarm,
  disconnect-disarm, and **loop_time 33–34 µs preserved** (gate adds no measurable cost).
- Not yet exercised live: the amplitude clamp path (needs a powered, in-range laser); covered
  by unit test. Tracked in todo.md.
- Design doc moved to `docs/old/2026-07-18-firmware-safety-stage-design.md`.
- Observation for David (pre-existing, not fixed): host-python CLI `_parse_values` always
  produces floats, so `helic-daq set diag_reset 1` / `set arm 1` raise a struct error for
  U32 params. The library `Device.set(name, 1)` (int) works, which is the intended arming
  path anyway (CLI one-shot disconnects → disarms). Worth a small CLI coercion fix separately.
- Remaining functional step for energised closed-loop: swap `ActiveController` PassThrough→PID.

## 2026-07-22T16:13+00:00 Safety-stage loopback commissioning agreed

- David connected DAC A to ADC0 positive and DAC C to ADC0 negative so ADC0
  directly measures the differential output. He confirmed that the exciter is
  disconnected or powered off and that the laser is powered with an in-range
  reading.
- The current helic-daq source is protocol v3 at `cd779ce`; the last safety
  image documented as flashed was protocol v2 at `c8c3abe`, so a clean rebuild
  and reflash are required before using the current host library.
- Agreed sequence: record the plan; create and simulator-test a fail-safe
  persistent-session test script; clean build and offline verification; flash
  and health check; disarmed baseline; low-level polarity/gain check;
  explicit-disarm and disconnect tests; bidirectional clamp test; verified
  quiet shutdown; analysis, plots, and documentation.
- Each step pauses for confirmation. The unrelated uncommitted helic-daq edit
  in `docs/rt_program_proposal.md` must be preserved, so reproducible firmware
  will be built from a clean detached worktree.
- A laser trip is not part of this run unless separately approved; do not
  manufacture one by changing calibration parameters.

## 2026-07-22T16:22+00:00 Loopback commissioning harness

- Added `src/scripts/commission_safety_loopback.py`, a phase-separated Python
  harness for the disarmed baseline, low-level mapping and sine capture,
  disconnect-disarm test, bidirectional clamp test, and final quiet check.
- Normal phases use a persistent control connection and disarm before clearing
  all output-producing paths in exception-safe cleanup. The disconnect phase
  deliberately closes while armed, then verifies quieting from a new control
  connection before cleanup.
- Acceptance checks cover firmware health counters, tick timing, UDP loss,
  record-drop growth, safety flags, output/ADC zero, loopback polarity/gain,
  clamp activation, and clamp symmetry. Rig amplitudes remain command-line
  inputs so `AGENTS.md` stays the source of truth.
- The protocol-v3 simulator self-test passed (160 records, zero loss/faults),
  exercising persistent control, streaming, data saving, loopback tracking,
  cleanup, and disconnect state. The simulator does not model the real safety
  gate, so clamp and disarmed-output acceptance remain hardware tests.

## 2026-07-22T16:25+00:00 Protocol-v3 clean build verification

- Created a clean detached helic-daq worktree at exact commit `cd779ce`; the
  main worktree's unrelated `docs/rt_program_proposal.md` edit remains intact.
- Passed root Rust formatting, all-target/all-feature clippy with warnings
  denied, and all tests (119 unit/integration tests plus doc tests). Passed all
  61 Python host tests and all 87 Julia host tests. MATLAB is not installed, so
  its tests remain unavailable.
- Passed release CBC clippy/build for W5500 and W6100. The firmware RT-layout
  gate now requires all three production ELFs; after building the complete
  firmware workspace it passed for CBC, whirl, and Pico 2W for both CBC board
  build states. Rebuilt W5500 last so the flash artifact matches the fitted
  board.
- The only warning was the already-documented future-incompatibility warning
  from the `proc-macro-error2` dependency. The clean worktree remained clean.

## 2026-07-22T16:27+00:00 Protocol-v3 image flashed and healthy

- Flashed the clean W5500 release image with the documented `cargo run` /
  `probe-rs run` path. The boot banner reported exactly `helic-daq 0.1.0
  cd779ce`; protocol-v3 discovery reported 41 parameters and 14 sources at
  8 kHz.
- Laser configuration completed normally and its first measurement was in
  range. Host checks observed approximately 24.818 mm.
- The post-reset gate was disarmed and untripped (`safety = 0b1000`): output
  was quieted but had neither tripped nor clamped.
- After resetting diagnostics, the attached and post-debugger-detachment
  checks both had zero overruns, tick timeouts, clock jitter, command backlog,
  record drops, and laser fault counters. Loop maximum was 35 us and wake
  phase was fixed at 36 us. The pre-reset startup/debugger history had an
  89 us wake maximum and was correctly excluded from the run baseline.

## 2026-07-22T16:27+00:00 Disarmed loopback baseline passed

- Captured 8000 full-rate records with all output sources zero and the safety
  gate disarmed. Applied `out` was exactly zero; ADC0 measured a -0.228 mV mean,
  0.083 mV standard deviation, and -0.534 to +0.076 mV range across A minus C.
- The laser remained at 24.816--24.823 mm. Safety stayed `0b1000` (disarmed,
  untripped, unclamped, quieted), the wake phase stayed at 36 us, loop maximum
  was 35 us, and every monitored fault/loss counter remained zero.
- Raw evidence and the machine-readable summary are under
  `data/2026-07-22-safety-loopback/`.

## 2026-07-22T16:28+00:00 Low-level differential mapping passed

- With a persistent armed connection, captured +50 mV and -50 mV constant
  commands and a 7 Hz, 0.1 Vpp sine through the A-minus-C to ADC0 loopback.
- The two constant captures fitted `adc0 = 1.000134 out - 0.269 mV`, with an
  0.084 mV RMS residual. This directly establishes the intended non-inverting
  differential polarity and near-unity gain at the fitted terminals.
- Applied output matched both constant commands and reached +/-50 mV on the
  sine. The gate stayed armed, untripped, and unclamped; all monitored fault
  and loss counters stayed zero, wake phase stayed at 36 us, and loop maximum
  was 38 us. Exception-safe cleanup then disarmed and cleared all generators.
