#!/usr/bin/env bash
#
# Verify a release is truly published: BOTH the remote tag and the GitHub
# Release must exist. Exits non-zero until both pass.
#
# Usage: verify_release.sh <version>
set -uo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "usage: verify_release.sh <version>" >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)" || exit 1
fail=0

echo "== remote tag =="
tag_line="$(git ls-remote --tags origin "refs/tags/${VERSION}" 2>/dev/null)"
if [ -n "$tag_line" ]; then
  echo "$tag_line"
  echo "TAG: present"
else
  echo "TAG: MISSING"
  fail=1
fi

echo "== github release =="
if command -v gh >/dev/null 2>&1; then
  if gh release view "${VERSION}" >/dev/null 2>&1; then
    echo "RELEASE: present"
  else
    echo "RELEASE: MISSING"
    fail=1
  fi
else
  echo "gh not installed — verify manually in the browser:"
  url_slug="$(git config --get remote.origin.url | sed -E 's#.*[/:]([^/]+/[^/]+?)(\.git)?$#\1#')"
  echo "  https://github.com/${url_slug}/releases/tag/${VERSION}"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✅ ${VERSION} is published (tag + Release both present)."
else
  echo "❌ ${VERSION} is NOT fully published yet."
fi
exit "$fail"
