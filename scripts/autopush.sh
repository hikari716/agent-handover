#!/usr/bin/env bash
# autopush.sh — commit & push this repo, honoring the agent-handover PAUSE brake.
#
# Designed to be called by an automation (launchd / cron / your fleet) after a
# session's changes land. It is idempotent and safe to run on every tick:
#   - does nothing when the working tree is clean
#   - refuses to push while a PAUSE file exists (human kill-switch)
#
# Config via env:
#   AH_BRANCH      (default: main)
#   AH_REMOTE      (default: origin)
#   AH_PAUSE_FILE  (default: $HOME/.agent_handover/PAUSE)
#   AH_MSG         (default: chore: auto-push <UTC timestamp>)
#
# Usage:  scripts/autopush.sh [REPO_DIR]
set -euo pipefail

REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${AH_BRANCH:-main}"
REMOTE="${AH_REMOTE:-origin}"
PAUSE_FILE="${AH_PAUSE_FILE:-$HOME/.agent_handover/PAUSE}"
MSG="${AH_MSG:-chore: auto-push $(date -u +%Y-%m-%dT%H:%M:%SZ)}"

cd "$REPO_DIR"

if [[ -e "$PAUSE_FILE" ]]; then
  echo "PAUSE present ($PAUSE_FILE) — skipping push." >&2
  exit 0
fi

if [[ -z "$(git status --porcelain)" ]]; then
  echo "nothing to commit — working tree clean."
  exit 0
fi

git add -A
git commit -m "$MSG"
git push "$REMOTE" "$BRANCH"
echo "pushed to $REMOTE/$BRANCH: $MSG"
