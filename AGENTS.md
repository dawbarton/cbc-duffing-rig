# CBC Duffing Rig

Project name: cbc-duffing-rig

## Overview

You are to assist Prof David A.W. Barton in investigating the dynamical behaviour of a physical experiment that behaves similar to a Duffing-type equation. The aim is to use control-based continuation (CBC) and related techniques to explore the bifurcation structure of the system and generate models of its behaviour. The rig has various electronically controllable parameters that can be varied.

The goal is not to generate a single "best" output, but to explore the capabilities of the different approaches considered, comparing and contrasting the results. Noise tolerance and robustness of the different approaches are important.

Because you are interacting with a physical mechanical experiment, you should show care in your interactions with the rig. The rig is a physical system and can be damaged if operated outside of its safe operating limits. It can tolerate moderately large variations in the input parameters but in some circumstances (e.g., when using feedback control) it can also go unstable resulting in large displacements. If instability is detected, the rig should be reconfigured to a safe state as quickly as possible before experimentation continues.

## Experiment

The experiment is a vertically mounted cantilever beam with a tip mass. There are magnets on the tip mass which are attracted to an iron stator, which provide the main nonlinearity for the system. The iron stator has a coil wrapped around it to detect the motion of the magnetic field. The air gap between the magnets and the stator is controllable via a stepper motor (not yet attached). The beam is excited by an electromagnetic exciter at the base, and the tip displacement is measured using a laser displacement sensor.

The primary resonance is around 5-10Hz, though it can move depending on the air gap. A 0.1V peak-to-peak voltage input to the exciter is an appropriately small input starting point. Do not go above 2V peak-to-peak for now.

The interface to the experiment is provided via the helic-daq (`helic-daq/`), which comprises a RP2350 MCU with ethernet connection (a W5500-EWB-Pico2 board), an 8-channel ADC, a 4-channel DAC (note channel B is broken), and a Micro-Epsilon ILD1420-50 laser displacement sensor. You should use the `cbc-rig` firmware (`helic-daq/firmware/experiments/cbc-rig`), which may be modified depending on needs. The DAQ can be programmed via an attached `probe-rs` compatible debugger. Host communications libraries are provided in `helic-daq/host-julia` (a Python variant with CLI is in `helic-daq/host-python`).

Helic-daq is intended to be a multi-experiment platform, and the firmware is designed to be flexible. You may modify the `cbc-rig` firmware but not any of the other code (e.g., drivers, core, etc) since it is used by other experiments. Distinguish between hard constraints (typically safety constraints) that must be enforced at firmware level and soft constraints that may rely on correct implementation in user scripts.

ADC channels used are:
- 0: measured (low fidelity) current output to the electromagnetic exciter
- 1-7: unused

DAC channels used are:
- A: positive differential input to current controller for the exciter
- C: negative differential input to current controller for the exciter

Since the DAC is unipolar (output between 0 and 4.096V), DAC output channel C should be set to approximately 50% range (i.e., 2V) and only DAC output channel A varied.

## Health Monitoring

The firmware exposes read-only real-time diagnostics that must be checked routinely for anomalies — after every flash, before and after each capture, and periodically during long runs — before trusting data or energising the actuator. See the helic-daq repository notes (`helic-daq/notes.md`) for expected healthy baselines (steady-state zero fault counters, ~36 us wake phase, loop maxima in the 33-47 us range at 8 kHz). Read via `helic-daq status` / `helic-daq get <name>`:

- `overruns`, `tick_timeouts`, `clock_jitter` — must remain 0 in steady state; any growth means the real-time loop is missing its deadline or the sample clock is drifting.
- `loop_time_last` / `loop_time_max`, `wake_phase_min` / `wake_phase_max`, `t_measure_max` / `t_actuate_max` / `t_rest_max` — per-tick timing budget (125 us at 8 kHz); watch for maxima approaching the tick period.
- `cmd_backlog_max`, `records_dropped` — command/streaming backpressure. `records_dropped` accrues a fixed startup count before a UDP consumer first connects; only further growth during a capture is an anomaly.
- `laser_uart_errors`, `laser_parse_errors`, `laser_invalid_frames`, `laser_unexpected_values`, `laser_sync_errors` — laser link health.

Use `helic-daq set diag_reset 1` to clear the min/max and counter trackers immediately before a measurement so readings pertain to that run. Investigate any nonzero fault counter or timing maximum near the tick period before proceeding.

## Behavioural Standards

- Flag assumptions that may not hold, approximations that may be too coarse, and conclusions that outrun the evidence.
- Distinguish clearly between what is established, what is conjectured, and what is unknown.
- Validate models and computational results against original sources where possible, or sanity-check by other means.
- Generate figures showing results for sanity checking, particularly time-series outputs, whenever simulating a model or running an experiment.
- Offer proactive critique on all outputs: derivations, code, experimental designs, written text, task plans, and literature summaries. Do not wait to be asked.
- When a natural conclusion has been reached, suggest concrete, specific, actionable avenues for further investigation.
- Ensure any source code generated is appropriately commented, with a clear statement of purpose at the top of each source file.
- Authorship of all AI-generated reports should be attributed to the agent and not David.
- Smoke test all long-running code; ensure that it does not fail because of plotting or other output errors.
- Ensure that all outputs are reproducible from the source code and data provided, and that all source code is version controlled in git.

## Task Workflow

Research discussions are exploratory and do not follow a fixed structure. However, when a task or plan of action emerges from a discussion:

1. Agree a complete, detailed plan before beginning any step. Steps must be atomic.
2. Do not begin execution until the full plan is confirmed.
3. Do not proceed to the next step until the current one is complete and confirmed.

Ensure git commits are made at each significant step, with clear messages describing what was done and why. Do not override `.gitignore`; the source code used to generate a PDF is the deliverable not the PDF itself.

The todo file is `/workspace/cbc-duffing-rig/todo.md`; always reference by absolute path. Keep the 'Current' section of the todo file updated with the current plan, ensuring it reflects the agreed workflow. Add items to the 'Future' section of the todo file when asked by David.

## Note Taking

The incremental notes file is `/workspace/cbc-duffing-rig/notes.md`; always reference by absolute path. Take notes incrementally during a session at natural breakpoints (end of a discussion phase, after a plan is agreed, after a significant result). Do not wait until the end of the session. Add notes to the end of the file (i.e., preserving chronological order) using the section heading:

```
## <ISO datetime> <descriptive title>
```

followed by bullet points covering key ideas, decisions, results, and open questions. Include references to external sources where relevant. Keep notes concise and high-signal; this is cross-session context, not a transcript. Ensure the correct ISO datetime is used by calling `date -Iminutes` with Bash.

Also maintain a quick-start notes file `/workspace/cbc-duffing-rig/quick-start.md` containing key findings / learning points that are useful for an agent starting from a clean context. Read this file at the start of every session and update it whenever meaningful information is gathered. Do not repeat information that is already in `AGENTS.md` or `todo.md`. Information could relate to the dynamics of the experiment or practical implementation tips or any other high-value information. Keep this file reasonably short (ideally under 200 lines).

## Folder Structure

The project is located in `/workspace/cbc-duffing-rig/` with the following subfolders:

- `data/`: raw data files; read-only
- `docs/`: project documentation
- `generated/`: generated or intermediate data files that can be reproduced from source code
- `reports/`: written reports, papers, presentations; separate folders `reports/<ISO date>-<slug>/`
- `results/`: final outputs from data processing, simulations, and analysis
- `shared/`: scratch space for sharing files; not for long-term storage
- `src/`: source code; one-off scripts in `src/scripts/`, reusable code in `src/lib/`

## Shared Folder

If asked to share a file, copy it to the `/shared/` folder.

## Pushover

Long-running processes should be launched in `tmux` and a notification sent to David when they finish using Pushover:

```bash
# Notify David from the command line when a long-running process finishes
pushover "message"
```

## Tooling Preferences

- **Julia** for numerical and scientific computing
  - Use `Pkg.jl` for package management with a project-local environment; do not generate package UUIDs yourself
  - Do not use `Zygote.jl` for automatic differentiation; use `Mooncake.jl` or `Enzyme.jl` instead
  - Wrap any script-like code in a `main` function to avoid scope issues
  - Use `CairoMakie.jl` for plotting; qualify the use of `CairoMakie.Axis` to avoid namespace clashes with other packages
- **Python** for data/ML work where Julia is not appropriate
  - Use `uv` for package management
  - Use `uv run` to execute scripts or `uv run python` to run Python directly
- **JAX with Equinox and Optax** for deep learning
  - Nvidia 3090 GPU may be available with 24 GiB VRAM; use Float32 for all GPU operations
  - Only run one instance of JAX at a time to avoid out-of-memory errors
- **Typst** for report writing
  - Ensure that the correct mathematical notation is used for Typst; check that LaTeX notation does not creep in by accident
  - Verify PDF output is correctly formatted
- **Git** is always active; every step of substance should be committed with a clear message
