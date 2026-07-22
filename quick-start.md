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
  more drive), then passed through the firmware safety gate (clamp + arm/trip).
  With the default `PassThrough` controller, `target` passes straight through.
- **Arming:** the output is **disarmed after every flash/reset** and stays at
  zero drive until you `set arm 1`; `set arm 0` or dropping the control
  connection disarms. Because each one-shot CLI command opens and closes its own
  connection (which disarms on close), driving the exciter needs a **persistent
  host session** (Julia/Python `Device` context) that arms once and holds the
  connection. Poll `safety` (bitfield: bit0 armed, bit1 tripped, bit2 clamped,
  bit3 quieted) to see gate state.
- `rig_out_channel` is locked to channel A (0) — leave it. `rig_laser_range`
  (mm) must match the fitted sensor (50 mm).

## Signals you can capture (`sources`)

- `adc0..adc7` (V) — `adc0` is the low-fidelity exciter current sense; `adc1-7`
  unused.
- `laser` (mm) — tip displacement.
- `target`, `forcing`, `table`, `out` (V) — the drive decomposition; `out` is
  the **applied** signed differential command, i.e. after the safety gate (clamp
  / quieting), so it reflects what was actually driven. (`out` is a source, not a
  parameter — capture it, don't `get` it.)
- `cmd_epoch` (count) — increments when a parameter write takes effect; capture
  it alongside data to align commands to samples.

## Safe operating points

- Exciter input: start at 0.1 V pp (amplitude 0.05 V); **do not exceed 2 V pp**.
  The firmware now hard-clamps the driven channel to a 0.096–4.0 V window
  (logical `out` ≈ ±1.952 V) and trips to quiet if the laser leaves the
  10–40 mm window or its feed stalls — but these are backstops, so still keep
  amplitude discipline host-side.
- Primary resonance ~5–10 Hz (shifts with the air gap).
- On any instability or large displacement, `set arm 0` (or drop the
  connection) to quiet the exciter immediately, and `stop` to zero forcing and
  target.

## Health check (each session, and around captures)

- See `AGENTS.md` "Health Monitoring". Quick version: `helic-daq set diag_reset
  1`, then confirm `overruns`/`tick_timeouts`/`clock_jitter` are ~0 and
  `loop_time_max` is well under 125 µs before trusting data.

## Sanity numbers

- Idle 8 kHz: `loop_time_max` ~33–35 µs, wake phase ~36 µs, fault counters 0,
  `clock_jitter` ~0–1 µs (the safety gate adds no measurable tick cost).
  `records_dropped` can have a fixed startup count from records produced before
  a UDP consumer connects — not an anomaly; watch for growth *during* a capture
  instead.
- With the laser unpowered, `safety` reads `0b1010` (tripped + quieting) — the
  correct blind-feedback default; once armed with a live laser in-range it reads
  `0b0001` (armed, not tripped).
- Protocol-v3 image `cd779ce` was commissioned through an A-minus-C to ADC0
  loopback on 2026-07-22: differential gain was 1.000134 with -0.269 mV offset;
  explicit and disconnect disarming both quieted a retained command; and both
  clamp directions matched applied-output telemetry. See `notes.md` and
  `results/2026-07-22-safety-loopback.png`.
- **Temporary fitted state (2026-07-22):** ADC0 is connected across DAC A and C
  for the commissioning loopback, not to its normal experiment signal. Restore
  the experiment wiring before interpreting ADC0 as the exciter current signal.
