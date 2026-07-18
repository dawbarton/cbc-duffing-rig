# Stability and Bifurcation Estimation (closed-loop)

Implementation guidance for agents. CBC/PLL let you *sit on* an orbit, but the stabilising
feedback masks the orbit's open-loop stability. This document covers how to recover the
open-loop stability and classify bifurcations from closed-loop input–output data, turning a
traced branch into a labelled bifurcation diagram.

## 1. Problem statement

On a converged, non-invasive CBC orbit the control action is ~zero, so the plant behaves as
open-loop *in the mean*, but you cannot infer stability from "we are sitting here" — the
controller supplied the stabilisation. To get the true (open-loop) Floquet multipliers you
must probe the *local linear dynamics around the orbit* and remove the known controller
contribution.

The orbit is periodic with period `T = 2π/ω`, so the linearisation is a **linear
time-periodic (LTP)** system. Stability is governed by the **monodromy matrix** `M` (the
state transition over one period); its eigenvalues are the **Floquet multipliers** `μ_i`.
Open-loop orbit is stable iff all `|μ_i| < 1` (discrete-time convention).

## 2. Local model identification

Inject a small broadband/multisine perturbation `d(t)` at the actuator (on top of the
non-invasive command) and record input `u(t)` and output `x(t)` fluctuations about the
orbit. Fit a **linear time-periodic** input–output model. Two established routes:

### (a) Periodic ARX (Barton 2017)
Fit an auto-regressive-with-exogenous-input model whose coefficients are periodic in the
orbit phase:
```
Σ_{k=0..na} a_k(θ_t) x_{t-k} = Σ_{k=0..nb} b_k(θ_t) u_{t-k} + e_t
```
where `θ_t = ω t mod 2π` is the phase and each coefficient is expanded in a Fourier series
in `θ`. Estimate the Fourier coefficients by least squares over many periods. Convert the
identified periodic ARX to a state-space LTP form and compute the monodromy `M` by
propagating over one period; its eigenvalues are the multipliers.

### (b) Hill / harmonic-transfer-function methods
Represent the LTP dynamics in the frequency domain via the harmonic transfer function and
extract multipliers from the Hill matrix. Heavier machinery; ARX is usually the pragmatic
experimental choice.

Remove the **known controller** from the identified loop: you identified the closed-loop
local dynamics, so subtract/deconvolve the (known) linear controller to recover the plant
multipliers. Equivalently, identify the plant directly by treating the injected `d(t)` as
the exogenous input and using the measured actuator command as the plant input.

## 3. Bifurcation detection and classification

Track the multipliers along the branch; a bifurcation occurs when one (or a pair) crosses
the unit circle:
- **`μ = +1`** (real, through +1): fold / saddle-node (also transcritical/pitchfork with
  symmetry). Coincides with the folds CBC passes via arclength.
- **`μ = −1`**: period-doubling (flip).
- **complex pair crossing `|μ| = 1`**: Neimark–Sacker (torus) / secondary Hopf.

Locate the crossing by interpolating the critical multiplier's magnitude to 1 along the
arclength coordinate. Record multiplier trajectories, not just the crossing, as evidence.

## 4. Practical considerations

- **Perturbation level**: large enough for identifiable SNR in the local model, small
  enough to stay in the linear regime around the orbit and not trip safety limits. Use a
  zero-mean multisine avoiding the controlled harmonics so it does not bias
  non-invasiveness.
- **Averaging / records**: LTP-ARX needs many periods for stable Fourier-coefficient
  estimates; budget acquisition accordingly.
- **Model order** (`na, nb`, number of phase-harmonics): choose by validation error /
  information criteria; too high fits noise, too low misses fast multipliers.
- **Consistency check**: at a fold detected by ARX, `μ → +1` should coincide with the
  arclength turning point in the branch geometry — cross-validate the two.
- **Cheaper proxies**: local convergence-rate / recurrence estimates around the orbit
  (Barton & Sieber) give a stability *indicator* without a full LTP model; useful for a
  quick pass, weaker for classification.

## 5. Algorithm

```
for each converged CBC orbit on the branch:
    inject small multisine d(t) at actuator (off the controlled harmonics)
    record u(t), x(t) over N periods
    fit periodic ARX (Fourier-in-phase coefficients) by least squares
    build LTP state space; propagate one period → monodromy M
    remove known controller contribution → open-loop multipliers μ_i
    store {μ_i}; flag |μ_i|→1 crossings and their type
```

## 6. References

- D. A. W. Barton, "Control-based continuation: Bifurcation and stability analysis for
  physical experiments", *Mech. Syst. Signal Process.* 84 (2017) 54–64. arXiv:1506.04052.
- D. A. W. Barton, J. Sieber, "Systematic experimental exploration of bifurcations with
  non-invasive control", *Phys. Rev. E* 87, 052916 (2013).
- N. M. Wereley, "Analysis and control of linear periodically time-varying systems", PhD,
  MIT (1990) — harmonic transfer functions / Hill methods background.
- A. Bittanti, P. Colaneri, *Periodic Systems: Filtering and Control*, Springer (2009) —
  LTP systems, Floquet theory, monodromy.
- G. Raze, G. Abeloos, G. Kerschen, "Experimental continuation in nonlinear dynamics:
  recent advances and future challenges" (2024). arXiv:2408.00138 — stability-estimation
  survey in the CBC context.

## Duffing rig

- Input `u` = logical differential drive to the exciter; output `x` = laser displacement.
  The injected multisine rides on top of the non-invasive command via the same firmware
  excitation path.
- At 5–10 Hz with 8 kHz sampling, one period is ~800–1600 samples; an LTP-ARX with a modest
  phase-harmonic expansion is well-resolved, but many periods are needed — expect
  tens-of-seconds captures per stability point. Watch `records_dropped`/`overruns` during
  these longer streams.
- Perturbation amplitude must respect the same soft/again-hard limits as everything else;
  keep the multisine small (well under the 0.1 Vpp working point) and confirm it does not
  push the tip past safe displacement. Trip to safe state on any excursion.
- Primary payoff for this rig: label the CBC-traced primary-resonance branch stable/unstable
  and pin the two saddle-node folds via `μ → +1`, cross-checked against the arclength
  turning points. Period-doubling/Neimark–Sacker are less expected near primary resonance
  but worth watching as forcing grows or the air gap narrows (stronger nonlinearity).
- The stator coil pickup gives an independent motion channel — useful as a validation
  output for the identified local model, separate from the laser.
