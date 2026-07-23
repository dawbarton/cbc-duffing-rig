# Branch-keyed data store

Experimental data and generated figures are **not** version-controlled (see the
repo `.gitignore`). This mechanism keeps that untracked data isolated per git
branch and out of git's way, so switching branches never mixes or clobbers the
outputs of different lines of work.

## How it works

- The real bytes live in an **external store** outside the repo:

  ```
  /workspace/cbc-duffing-rig-data/<branch>/{data,results,generated}
  ```

- Inside the repo, `data/`, `results/`, and `generated/` are **symlinks** into
  the current branch's bucket. Scripts read and write `data/` etc. exactly as
  before — they never need to know about the store.

- A committed **`post-checkout` hook** (`.githooks/post-checkout`) repoints those
  symlinks to match whichever branch you check out, creating the bucket on
  demand. Switch branch → the data swaps underneath you, with no git-tracked
  file changing. A detached HEAD gets its own `detached-<sha>` bucket.

The symlinks themselves are gitignored (anchored `/data`, `/results`,
`/generated` entries — trailing-slash patterns do not match symlinks), so git
never tracks them.

## Activation (run once per clone)

The hook is versioned, but its activation (`core.hooksPath`) lives in local
`.git/config` and does not travel with a clone. After cloning, run:

```bash
src/scripts/data-store/setup-data-store.sh
```

This migrates any existing `data/ results/ generated/` directories into the
current branch's bucket, replaces them with symlinks, and activates the hook.
It is idempotent — safe to re-run.

## Configuration

The store root defaults to `/workspace/cbc-duffing-rig-data`. To override,
create `.cbc-data.env` at the repo root (it is not version-controlled):

```bash
DATA_ROOT="/some/other/location"
```

Both the hook and the setup script source this file if present.

## Provenance

Branch identity is mutable, so per-branch isolation is for *organisation*, not
*provenance*. For provenance, each experimental run must record the producing
commit in a `run_manifest.txt` inside its output folder — see the
"Data Provenance" section of `AGENTS.md`.

## Caveats

- New branches (and `main`) start with empty buckets; past runs are **not**
  retroactively separated (they were never distinguished on disk).
- The hook never overwrites a real directory — if it finds one where a symlink
  is expected, it warns and leaves it alone. Run the setup script to migrate.
