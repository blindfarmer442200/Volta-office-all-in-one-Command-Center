---
name: cut-release
description: Cut a versioned GitHub release for this repo — create an ANNOTATED git tag on a target commit, push it, then create a GitHub Release from that existing tag using a notes file (default RELEASE.md). Use when asked to tag, cut, publish, or release a version (e.g. "release v0.1.0", "cut v0.2.0", "publish the tag"). Handles sandboxes that cannot push tags or lack the gh CLI by emitting a ready-to-run local script and a verifier instead of silently failing.
---

# cut-release

Publish a version as an **annotated tag + GitHub Release**, in the correct order,
and verify it actually landed. This encodes the release procedure so it is
repeatable and never silently half-done.

## The invariant: annotated tag first, Release second

Always create the **annotated** tag (`git tag -a`) and push it BEFORE creating
the Release. If you create the Release first (web "Draft a new release" or
`gh release create <v>` with no existing tag), GitHub mints a **lightweight**
tag and the annotation (tagger, date, message) is lost. Order is non-negotiable:

1. `git tag -a <version> <commit> -m "<title>"`
2. `git push origin <version>`
3. `gh release create <version> --title "<title>" --notes-file <notes>`

## The gate: a release is only "done" when BOTH checks pass

```
git ls-remote --tags origin <version>   # prints the tag ref
gh release view <version>               # shows the Release
```

Never report a version as "published"/"released" until you have personally
seen both return real output. Merged ≠ released.

## How to run it

1. Confirm the target commit is merged and green. Default target is the current
   `origin/main` HEAD; override with an explicit commit SHA if the caller names one.
2. Confirm the notes file exists (default `RELEASE.md`).
3. Run `scripts/cut_release.sh <version> [target_commit] [notes_file] [title]`.
   - It creates the annotated tag, pushes it, and creates the Release.
   - It is idempotent: it skips the tag if it already exists and skips the
     Release if it already exists.
4. Run `scripts/verify_release.sh <version>` and confirm BOTH checks pass.

## When the environment cannot finish it (sandbox limits)

Some sandboxes reject tag pushes (git proxy returns HTTP 403 on `refs/tags/*`
while allowing branch pushes) or have no `gh` CLI. `cut_release.sh` detects both
and stops with a clear message instead of pretending success. In that case:

- Do NOT claim the release is published.
- Hand the caller the exact commands to run from a terminal logged into their
  GitHub account (the script prints them, or copy the block below), then wait.
- After they run it, verify from your side with the repo's read tools
  (`list_tags` + `get_release_by_tag`) or `scripts/verify_release.sh`.

```bash
git fetch origin && git checkout main && git pull origin main
git tag -a <version> <commit> -m "<title>"
git push origin <version>
gh release create <version> --title "<title>" --notes-file <notes>
```

## Files

- `scripts/cut_release.sh` — annotated tag → push → Release, idempotent, sandbox-aware.
- `scripts/verify_release.sh` — runs the two-check gate and exits non-zero until both pass.
