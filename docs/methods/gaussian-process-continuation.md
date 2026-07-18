# Gaussian-Process-Regression Continuation

Implementation guidance for agents. This method surrogates the experimental response
locally with **Gaussian-process (GP) regression**, giving smooth derivative (Jacobian)
estimates *and* calibrated uncertainty from noisy rig data. It is the natural tool for the
project's noise-robustness/UQ emphasis, and a drop-in replacement for the finite-difference
Jacobian in standard CBC.

## 1. Motivation

The corrector in CBC needs `J = ∂G/∂u` (see `control-based-continuation.md`). Finite
differences are noisy and expensive; Broyden can stall. A GP fitted to a local cloud of
`(u, G(u))` evaluations provides:
- a **smoothed mean** residual/response (denoising),
- **analytic derivatives** of the GP mean (a Jacobian without extra perturbation
  experiments), and
- a **posterior variance** (uncertainty on the branch and on bifurcation locations).

## 2. Method

1. **Local dataset**: collect rig evaluations `{(u_j, y_j)}` near the current branch point,
   where `y_j` is the measured response/residual (harmonic coefficients). Reuse points
   already visited by the continuation — no dedicated finite-difference perturbations.
2. **GP model**: place a GP prior on each output component,
   `y(u) ~ GP(m(u), k(u,u'))`, typically a squared-exponential or Matérn kernel with an
   observation-noise term `σ_n²` matched to the measured rig noise. Fit hyperparameters
   (lengthscales, signal/noise variances) by marginal-likelihood maximisation on the local
   set.
3. **Prediction + derivative**: the GP posterior mean and its gradient are closed-form; use
   the gradient as the Jacobian `J` in the Newton/arclength corrector, and the posterior
   variance to weight steps and to put error bars on the located solution.
4. **Local, moving window**: keep the GP *local* (a sliding window along the branch) so the
   surrogate stays cheap and valid; refit as the window advances. This is "numerical
   continuation in experiments using local GP regression".
5. **Active sampling** (optional): choose the next rig evaluation to maximise information
   (reduce posterior variance where it matters for the corrector), improving sample
   efficiency.

## 3. Uncertainty quantification

Because every predicted response carries a posterior variance, you get:
- **Confidence bands** on the traced branch.
- **Uncertainty on bifurcation points** (propagate variance to the fold/multiplier
  condition).
- A principled **stopping/refinement rule**: sample more where variance is high near the
  feature of interest.

This is the main differentiator versus finite-difference or Broyden Jacobians, which give a
point estimate with no calibrated uncertainty.

## 4. Practical considerations

- **Noise term**: set `σ_n²` from a measured repeatability estimate (repeat the same `u`,
  observe scatter); a wrong noise level makes the GP over- or under-smooth.
- **Input scaling**: `ω` and harmonic amplitudes have different scales — normalise inputs so
  a single/anisotropic lengthscale is meaningful.
- **Window size**: too small → derivatives noisy; too large → surrogate misfits curvature at
  folds. Adapt to local curvature.
- **Cost**: GP fitting is O(N³) in window points — keep windows small (tens of points), use
  local sets, not the whole branch history.
- **Libraries**: any standard GP implementation; keep it host-side (Julia) alongside the
  corrector.

## 5. Algorithm

```
maintain sliding window W of visited points (u_j, y_j) near the front
at each continuation step:
    fit local GP to W (optimise hyperparameters, fixed noise σ_n from rig repeatability)
    corrector: use GP posterior mean gradient as Jacobian J in Newton/arclength step
    request new rig evaluation(s) (optionally active-sampling to cut variance)
        safety check each evaluation: limits, else abort → safe state
    add point to W; slide window; propagate posterior variance to branch/bifurcation bands
```

## 6. References

- L. Renson, D. A. W. Barton, S. A. Neild, "Numerical continuation in nonlinear experiments
  using local Gaussian process regression", *Nonlinear Dynamics* 98 (2019).
- C. E. Rasmussen, C. K. I. Williams, *Gaussian Processes for Machine Learning*, MIT Press
  (2006) — GP regression, derivatives, marginal likelihood.
- G. Raze, G. Abeloos, G. Kerschen, "Experimental continuation in nonlinear dynamics:
  recent advances and future challenges" (2024). arXiv:2408.00138 — surrogate/UQ methods in
  the CBC context.

## Duffing rig

- Directly serves the project's noise-tolerance and robustness brief: it both denoises the
  Jacobian and attaches uncertainty to the traced branch and to fold locations — quantities
  worth reporting in the method comparison.
- Reuses the standard-CBC non-invasive residual and the firmware Fourier/table excitation
  unchanged; only the corrector's Jacobian source changes. Implement host-side in Julia.
- Set the GP noise term from a measured rig repeatability at a fixed operating point (repeat
  the same reference, observe laser-harmonic scatter) rather than guessing — the high-rate
  streaming makes such repeatability captures cheap.
- Especially useful near the primary-resonance folds where finite-difference Jacobians are
  worst-conditioned; the posterior variance gives an honest error bar on the fold location
  vs air gap.
- Same closed-loop safety envelope as CBC (drive through the exciter); active-sampling must
  still respect amplitude limits and trip to the safe state on any excursion.
- Natural pairing: use GP-Jacobian CBC and derivative-free arclength CBC as the two
  "Jacobian-avoiding vs Jacobian-approximating" arms of the robustness comparison against
  baseline finite-difference CBC.
