#!/usr/bin/env bash
# Commit everything, bump versions, tag and push. GitHub Actions then builds the .deb + .apk
# and publishes them as a GitHub Release.
#
#   bash scripts/release.sh v0.2.0 "Fix black screen on Tab A7, 0-FPS freeze, top-bar guard"
set -euo pipefail

VER="${1:?usage: release.sh vX.Y.Z [commit message]}"
MSG="${2:-Release $VER}"
[[ "$VER" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must look like v1.2.3" >&2; exit 1; }

cd "$(dirname "$0")/.."
git rev-parse --is-inside-work-tree >/dev/null
git remote get-url origin >/dev/null || { echo "no 'origin' remote — run: git remote add origin git@github.com:<you>/gitdesk.git" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/$VER" >/dev/null && { echo "tag $VER already exists" >&2; exit 1; }

NUM="${VER#v}"
sed -i "s/^__version__ = .*/__version__ = \"$NUM\"/" server/gitdesk/__init__.py
sed -i "s/versionName = \".*\"/versionName = \"$NUM\"/" android/app/build.gradle.kts
CODE=$(( $(git rev-list --count HEAD 2>/dev/null || echo 0) + 2 ))
sed -i "s/versionCode = [0-9]*/versionCode = $CODE/" android/app/build.gradle.kts

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git add -A
git diff --cached --quiet || git commit -m "$MSG"
git tag -a "$VER" -m "$MSG"
git push origin "$BRANCH"
git push origin "$VER"

REPO="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
echo "Pushed $VER. Build + release: https://github.com/$REPO/actions"
