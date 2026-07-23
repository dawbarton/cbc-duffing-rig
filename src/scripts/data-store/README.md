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

- Inside the repo, `data/`, `results/`, and `generated/` are **relative
  symlinks** into the current branch's bucket (e.g.
  `data -> ../cbc-duffing-rig-data/<branch>/data`). Scripts read and write
  `data/` etc. exactly as before — they never need to know about the store. The
  links are relative so they resolve on any machine, independent of absolute
  paths.

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

## Copying to another machine

The symlinks are **relative**, so portability just needs the repo and its
sibling store copied together with their layout preserved:

```
<somewhere>/cbc-duffing-rig/          (the repo)
<somewhere>/cbc-duffing-rig-data/     (the store, sibling of the repo)
```

Copy both (e.g. `rsync -a` the parent, or both dirs) and the links resolve with
no path fix-up. `git clone` alone never brings the store (it is untracked) — run
the setup script afterwards, then copy the store in.

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
