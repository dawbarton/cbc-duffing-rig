#!/usr/bin/env bash
#
# setup-data-store.sh: one-time activation of the branch-keyed data store
# -----------------------------------------------------------------------
# Purpose: run once per clone. Migrates any real data/ results/ generated/
# directories in the working tree into the current branch's bucket inside the
# external store, replaces them with symlinks, and activates the post-checkout
# hook (via core.hooksPath) so future branch switches keep the data isolated.
#
# Idempotent: safe to re-run. Already-migrated paths (symlinks) are left as-is;
# a real directory is migrated only if its bucket target does not already exist.
#
# See docs: AGENTS.md "Data Provenance" and ./README.md

set -euo pipefail

DATA_ROOT="/workspace/cbc-duffing-rig-data"
repo_root="$(git rev-parse --show-toplevel)"
[ -f "$repo_root/.cbc-data.env" ] && . "$repo_root/.cbc-data.env"

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [ -z "$branch" ]; then
    branch="detached-$(git rev-parse --short HEAD)"
fi
bucket="$DATA_ROOT/$branch"

echo "Data store root : $DATA_ROOT"
echo "Current branch  : $branch"
echo "Bucket          : $bucket"
echo

mkdir -p "$bucket"

for name in data results generated; do
    link="$repo_root/$name"
    target="$bucket/$name"
    # Relative target (lexical, -sm) so the repo+store pair is portable across
    # machines; see .githooks/post-checkout and README.md.
    rel_target="$(realpath -sm --relative-to="$repo_root" "$target")"

    if [ -L "$link" ]; then
        # Already a symlink: re-point it to the correct relative target. This
        # makes the script self-healing and idempotent — e.g. it converts a
        # previously absolute link to a relative one.
        mkdir -p "$target"
        ln -sfn "$rel_target" "$link"
        echo "  $name: normalised existing symlink -> $rel_target"
        continue
    fi

    if [ -e "$link" ] && [ ! -d "$link" ]; then
        echo "  $name: exists but is neither a directory nor a symlink; skipping (inspect manually)." >&2
        continue
    fi

    if [ -d "$link" ]; then
        if [ -e "$target" ]; then
            echo "  $name: bucket target already exists ($target); refusing to overwrite. Resolve manually." >&2
            continue
        fi
        echo "  $name: migrating real directory -> $target"
        mv "$link" "$target"
    else
        echo "  $name: no existing directory; creating empty bucket target."
        mkdir -p "$target"
    fi

    ln -sfn "$rel_target" "$link"
    echo "  $name: symlink created -> $rel_target"
done

echo
echo "Activating post-checkout hook (core.hooksPath = .githooks)"
git -C "$repo_root" config core.hooksPath .githooks
chmod +x "$repo_root/.githooks/post-checkout"

echo
echo "Done. Verify with: git check-ignore -v data results generated"
