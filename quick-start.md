# CBC Duffing Rig quick start

Read `AGENTS.md` first (experiment description, channel roles, safety limits,
health monitoring). This file is how to **run experiments**, assuming the
`cbc-rig` firmware is fixed. To build, flash, or change the firmware — or for the
DAC/signal internals — see `docs/firmware-guide.md`.

## Talking to the DAQ

- Device: `cbc-rig` at static IP `192.168.1.235`.
- Python CLI, from `helic-daq/host-python`:
  `uv run --python 3.12 helic-daq <cmd>`
  - `status`, `list`, `sources` — device state, parameters, capturable signals.
  - `get <names...>`, `set <name> <val>` — read/write parameters.
  - `sine <freq> <amp>` — sinusoidal forcing smoke test; `stop` — zero forcing
    and target.
  - `capture --sources a,b,c --seconds N [--decimation D] [--output f.npz]`.
  - `find` — discover devices on the network.
- Julia host library is in `helic-daq/host-julia` (preferred for analysis, per
  the project tooling conventions).

## Driving the experiment

- Excitation is a Fourier series played at fundamental frequency `freq` (Hz):
  - `forcing_coeffs` / `target_coeffs` have length 33 = `[mean, a1..a16,
    b1..b16]` (cosine `a_k`, sine `b_k`). The `sine` helper just sets one `b_k`.
  - Arbitrary waveforms: upload a `table` and set `table_len`, `table_freq`,
    `table_gain`, `table_interp`, `table_mode`, `table_mult`, `table_phase`,
    `table_trigger` (see `helic-daq/docs/user_guide.md`).
- The applied exciter command is `out = controller(target) + forcing + table`,
  in volts as the **signed differential drive** (0 V = zero drive, positive =
  more drive). With the default `PassThrough` controller, `target` passes
  straight through.
- `rig_out_channel` is locked to channel A (0) — leave it. `rig_laser_range`
  (mm) must match the fitted sensor (50 mm).

## Signals you can capture (`sources`)

- `adc0..adc7` (V) — `adc0` is the low-fidelity exciter current sense; `adc1-7`
  unused.
- `laser` (mm) — tip displacement.
- `target`, `forcing`, `table`, `out` (V) — the drive decomposition; `out` is
  the applied signed differential command. (`out` is a source, not a parameter —
  capture it, don't `get` it.)
- `cmd_epoch` (count) — increments when a parameter write takes effect; capture
  it alongside data to align commands to samples.

## Safe operating points

- Exciter input: start at 0.1 V pp (amplitude 0.05 V); **do not exceed 2 V pp**.
  A logical `out` beyond ±2.048 V saturates at the DAC and is **not** clamped by
  firmware — enforce amplitude limits host-side.
- Primary resonance ~5–10 Hz (shifts with the air gap).
- On any instability or large displacement, `stop` immediately (zeros forcing
  and target).

## Health check (each session, and around captures)

- See `AGENTS.md` "Health Monitoring". Quick version: `helic-daq set diag_reset
  1`, then confirm `overruns`/`tick_timeouts`/`clock_jitter` are ~0 and
  `loop_time_max` is well under 125 µs before trusting data.

## Sanity numbers

- Idle 8 kHz: `loop_time_max` ~33–35 µs, wake phase ~36 µs, fault counters 0,
  `clock_jitter` ~0–1 µs. `records_dropped` sits at a fixed ~498 startup count
  (records produced before a UDP consumer connects) — not an anomaly; watch for
  growth *during* a capture instead.
