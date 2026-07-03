#!/usr/bin/env bash
#
# Cut a versioned release: annotated tag -> push -> GitHub Release.
#
# Usage: cut_release.sh <version> [target_commit] [notes_file] [title]
#   version        e.g. v0.1.0
#   target_commit  commit the tag points at (default: current origin/main HEAD)
#   notes_file     Release body (default: RELEASE.md)
#   title          Release title (default: "<repo> <version>")
#
# Idempotent: skips the tag if it already exists, skips the Release if it exists.
# Sandbox-aware: if the tag push is rejected (HTTP 403 on refs/tags/*) or gh is
# missing, it stops with the exact manual commands instead of faking success.
set -uo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "usage: cut_release.sh <version> [target_commit] [notes_file] [title]" >&2
  exit 2
fi
TARGET_ARG="${2:-}"
NOTES="${3:-RELEASE.md}"

cd "$(git rev-parse --show-toplevel)" || exit 1
REPO="$(basename "$(git rev-parse --show-toplevel)")"
TITLE="${4:-${REPO} ${VERSION}}"

echo ">> syncing origin"
git fetch origin --tags || true

TARGET="${TARGET_ARG:-$(git rev-parse origin/main)}"
echo ">> version=${VERSION} target=${TARGET} notes=${NOTES}"

if [ ! -f "$NOTES" ]; then
  echo "ERROR: notes file '$NOTES' not found" >&2
  exit 1
fi

# 1) Annotated tag (idempotent)
if git rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null; then
  echo ">> local tag ${VERSION} already exists -> $(git rev-list -n1 "${VERSION}")"
else
  echo ">> creating annotated tag ${VERSION}"
  git tag -a "${VERSION}" "${TARGET}" -m "${TITLE}" || exit 1
fi

# 2) Push tag
echo ">> pushing tag ${VERSION}"
if ! git push origin "${VERSION}"; then
  cat >&2 <<EOF

!! Could not push the tag from this environment (likely a sandbox that blocks
!! refs/tags/* with HTTP 403). The annotated tag exists LOCALLY and is correct.
!! Finish from a terminal logged into your GitHub account:

  git push origin ${VERSION}
  gh release create ${VERSION} --title "${TITLE}" --notes-file ${NOTES}

Then verify:  scripts/verify_release.sh ${VERSION}
EOF
  exit 3
fi

# 3) Create the Release from the existing tag
if ! command -v gh >/dev/null 2>&1; then
  cat >&2 <<EOF

!! Tag pushed, but the gh CLI is not installed here, so the Release wasn't
!! created. Create it from a terminal with gh:

  gh release create ${VERSION} --title "${TITLE}" --notes-file ${NOTES}

Then verify:  scripts/verify_release.sh ${VERSION}
EOF
  exit 4
fi

if gh release view "${VERSION}" >/dev/null 2>&1; then
  echo ">> Release ${VERSION} already exists — nothing to do"
else
  echo ">> creating GitHub Release ${VERSION}"
  gh release create "${VERSION}" --title "${TITLE}" --notes-file "${NOTES}" || exit 1
fi

echo ">> done. verifying..."
exec "$(dirname "$0")/verify_release.sh" "${VERSION}"
