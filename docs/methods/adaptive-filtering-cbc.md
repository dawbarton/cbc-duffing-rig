# Adaptive-Filtering (Continuous-Time) CBC

Implementation guidance for agents. This is a reformulation of CBC that replaces the
discrete "measure → project → Newton on Fourier coefficients" loop with a **continuous-time
adaptive controller** that drives the control non-invasive online. It is the noise-robust,
faster-to-run variant and the natural basis for the project's stepped-vs-swept robustness
comparison.

## 1. Principle

Standard CBC (see `control-based-continuation.md`) alternates between measuring harmonics
and taking discrete Newton steps on the reference. Adaptive-filtering CBC instead runs an
online estimator that continuously identifies the response harmonics and updates the
reference so that the invasive (error) harmonics decay to zero in real time. Non-invasiveness
becomes an *asymptotic property of a continuously running loop* rather than the solution of
a discrete root-finding problem.

Conceptually: an adaptive filter (LMS or recursive-least-squares) maintains estimates of the
Fourier coefficients of the tracking error at the drive frequency and its harmonics; the
reference is adapted to cancel them. As the orbit settles, the adapted correction → 0 and
the controller is non-invasive.

## 2. Harmonic adaptive control

Maintain a regressor of the controlled harmonics at frequency `ω`:
```
φ(t) = [cos ωt, sin ωt, cos 2ωt, sin 2ωt, …, cos Hωt, sin Hωt]^T
```
Estimate the error harmonic vector `ŵ` and adapt (LMS form):
```
e(t)  = x(t) − r(t)
ŵ    ← ŵ + μ · e(t) · φ(t)        (μ: adaptation gain / step size)
r(t)  = r_target(t) + correction(ŵ, φ)
```
An RLS form replaces the fixed step `μ` with a covariance update and a **forgetting factor**
`λ ∈ [0.99, 0.9999]` to track slowly time-varying orbits. The adaptation cancels the error
harmonics, i.e. enforces `G(u)=0` continuously rather than at discrete Newton iterates. This
is closely related to adaptive feedforward cancellation / higher-harmonic control.

Frequency `ω` is either imposed or tracked (a phase estimator / PLL-like inner loop refines
it — see `phase-locked-loop.md`), which is why this family sits close to PLL methods.

## 3. Stepped vs swept continuation

- **Stepped**: hold the continuation parameter (e.g. forcing amplitude or frequency), let
  the adaptive loop settle to non-invasiveness, record the point, then step the parameter.
  Cleaner steady-state per point; slower.
- **Swept**: ramp the continuation parameter slowly *while the adaptive loop tracks*,
  recording continuously. Much faster and gives dense branches, but each point is only
  quasi-steady-state — the ramp rate must be slow relative to the adaptation/settling time
  or the branch is biased (dynamic hysteresis). Validate the ramp rate by halving it and
  checking the branch is unchanged.

Both require a stabilising base controller; the adaptive layer handles non-invasiveness.
Passing folds under a swept protocol needs an arclength-like parameterisation (ramp the
arclength, not a single physical parameter) — combine with
`derivative-free-arclength-cbc.md`.

## 4. Tuning

- **Adaptation gain `μ` (LMS)** or **forgetting factor `λ` (RLS)**: large `μ` / small `λ`
  → fast tracking, more noise sensitivity, risk of instability; small `μ` / large `λ` →
  robust but slow. Scale `μ` inversely with signal power (normalised LMS) for consistent
  behaviour across amplitude.
- **Number of harmonics `H`**: as in standard CBC — enough to capture the physical
  harmonics, no more (odd harmonics dominate for Duffing-type nonlinearity).
- **Base-controller gains**: set for stabilisation/margins; the adaptive layer should be
  slower than the stabilising loop so the two do not interact.
- **Ramp rate (swept)**: the key robustness knob; set from the measured adaptation settling
  time.

## 5. Noise robustness

The continuous estimator performs implicit temporal averaging (LMS/RLS minimise mean-square
error), giving graceful degradation with SNR and tolerance to sample jitter, versus the
discrete Newton loop's need for clean, synchronised harmonic snapshots. Quantitative SNR
thresholds quoted in the literature should be treated as indicative and re-measured on the
rig. This noise behaviour is the main reason to include the method in the project's
robustness comparison.

## 6. Algorithm (swept)

```
initialise base controller, ŵ ← 0, ω, small amplitude
enable adaptive harmonic cancellation loop (LMS/RLS)
ramp continuation parameter slowly:
    each tick: e = x − r; ŵ ← adapt(ŵ, e, φ); r = r_target + corr(ŵ, φ)
    periodically log (parameter, ω, harmonics X, control power)
    safety check every tick: displacement/current in limits, else abort → safe state
validate: repeat at half ramp rate; branches must coincide
```

## 7. References

- G. Abeloos, L. Renson, C. Collette, G. Kerschen, "Stepped and swept control-based
  continuation using adaptive filtering", *Nonlinear Dynamics* 104 (2021).
- "Model-free continuation of periodic orbits in certain nonlinear systems using
  continuous-time adaptive control" (2022). arXiv:2203.10306.
- G. Raze, G. Abeloos, G. Kerschen, "Experimental continuation in nonlinear dynamics:
  recent advances and future challenges" (2024). arXiv:2408.00138.
- Background: adaptive feedforward cancellation / higher-harmonic control literature
  (e.g. Bodson, Sacks, Khosla on adaptive rejection of periodic disturbances).

## Duffing rig

- Fits the deterministic real-time loop well: the harmonic regressor `φ(t)` is cheap
  to evaluate per tick, and an LMS/RLS update on `H≈3` harmonics is a small fixed cost. A
  first implementation can keep the adaptive law host-side over the streaming interface;
  moving it into `cbc-rig` firmware later would cut latency but is a shared-code change to
  scope with David.
- Swept mode is attractive for quickly mapping the primary-resonance frequency response vs
  air gap; always run the half-ramp-rate validation before trusting a swept branch.
- Same closed-loop safety envelope as CBC/PLL (drive through the exciter): amplitude ceiling,
  arming/lease, comms-loss and ADC-fault quieting, per-tick safety trip to safe state.
  A continuously running adaptive loop makes comms-loss quieting especially important —
  a dropped host link must not leave the loop adapting blind.
- This variant is the recommended vehicle for the project's explicit noise-tolerance axis:
  compare stepped adaptive-filtering CBC, swept adaptive-filtering CBC, and discrete
  Newton CBC on the same operating point and quantify branch scatter vs acquisition time.
