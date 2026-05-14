#!/usr/bin/env bash
# agents/orchestrator/scripts/pr_merge_watcher.sh
#
# Watches all grava issues labeled `pr-created` and handles PR lifecycle:
#   MERGED  → grava close, PIPELINE_COMPLETE signal
#   CLOSED  → label pr-rejected, record rejection notes
#   OPEN    → check stale (>72h), detect new review comments
#
# Run as cron (from inside the target repo):
#   */5 * * * * cd /path/to/target-repo && \
#     bash /path/to/stellar-engine/agents/orchestrator/scripts/pr_merge_watcher.sh
#
# Reads team wisp to emit correct re-entry hint per team.

set -u

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$REPO_ROOT" || { echo "[watcher] cd failed: $REPO_ROOT"; exit 1; }

MAX_PR_WAIT_HOURS=72
NOW=$(date -u +%s)

# --- Singleton guard ---
PIDFILE=".grava/orchestrator-pr-watcher.pid"
mkdir -p .grava
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[watcher] already running (pid=$OLD_PID)"
    exit 0
  fi
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

# --- Fetch all issues labeled pr-created ---
ISSUES_JSON=$(grava list -L pr-created --json 2>/dev/null)
if [ -z "$ISSUES_JSON" ] || [ "$ISSUES_JSON" = "[]" ] || [ "$ISSUES_JSON" = "null" ]; then
  exit 0
fi

echo "$ISSUES_JSON" | command -p python3 -c "
import json, sys
data = json.load(sys.stdin)
for item in data:
    iid = item.get('id') or item.get('ID', '')
    if iid:
        print(iid)
" | while read -r ID; do
  [ -n "$ID" ] || continue

  PR_NUMBER=$(grava wisp read "$ID" pr_number 2>/dev/null || true)
  PR_URL=$(grava wisp read "$ID" pr_url 2>/dev/null || true)
  TEAM=$(grava wisp read "$ID" team 2>/dev/null || true)

  [ -n "$PR_NUMBER" ] || { echo "[watcher] $ID: no pr_number wisp, skipping"; continue; }

  STATE=$(gh pr view "$PR_NUMBER" --json state -q '.state' 2>/dev/null || echo "UNKNOWN")

  case "$STATE" in
    MERGED)
      echo "[watcher] $ID: PR #$PR_NUMBER merged"
      grava wisp write "$ID" pr_merged_at "$NOW" 2>/dev/null || true
      grava signal PR_MERGED --issue "$ID" --actor watcher 2>/dev/null || \
        grava wisp write "$ID" pipeline_phase complete
      grava label "$ID" --remove pr-created 2>/dev/null || true
      grava close "$ID" --actor watcher 2>/dev/null || true
      grava signal PIPELINE_COMPLETE --issue "$ID" --payload "$ID" --actor watcher 2>/dev/null || \
        grava wisp write "$ID" pipeline_phase complete
      grava commit -m "watcher: $ID merged + closed (team=${TEAM:-unknown})" 2>/dev/null || true
      ;;

    CLOSED)
      ALREADY=$(grava wisp read "$ID" pr_rejection_recorded 2>/dev/null || true)
      if [ -z "$ALREADY" ]; then
        REVIEW_DECISION=$(gh pr view "$PR_NUMBER" --json reviewDecision \
          -q '.reviewDecision' 2>/dev/null || echo "")
        REASON="closed without merge"
        [ -n "$REVIEW_DECISION" ] && REASON="$REVIEW_DECISION"

        echo "[watcher] $ID: PR #$PR_NUMBER closed ($REASON)"
        grava signal PR_CLOSED --issue "$ID" --payload "$REASON" --actor watcher 2>/dev/null || \
          grava wisp write "$ID" pipeline_phase failed
        grava wisp write "$ID" pr_rejection_recorded "1" 2>/dev/null || true
        grava wisp write "$ID" pr_rejection_reason "$REASON" 2>/dev/null || true
      fi

      grava label "$ID" --add pr-rejected 2>/dev/null || true
      grava label "$ID" --remove pr-created 2>/dev/null || true
      grava commit -m "watcher: $ID PR closed without merge (team=${TEAM:-unknown})" 2>/dev/null || true

      # Re-entry hint per team
      case "$TEAM" in
        fix-bug)   echo "[watcher] $ID (fix-bug): run /deploy $ID --retry to re-fix" ;;
        epic-task) echo "[watcher] $ID (epic-task): run /ship $ID --retry to address review" ;;
        *)         echo "[watcher] $ID ($TEAM): PR rejected — manual intervention needed" ;;
      esac
      ;;

    OPEN)
      # Stale cap check
      SINCE=$(grava wisp read "$ID" pr_awaiting_merge_since 2>/dev/null || true)
      [ -n "$SINCE" ] || SINCE="$NOW"
      AGE_HRS=$(( (NOW - SINCE) / 3600 ))
      if [ "$AGE_HRS" -ge "$MAX_PR_WAIT_HOURS" ]; then
        ALREADY_STALE=$(grava wisp read "$ID" pr_stale 2>/dev/null || true)
        if [ -z "$ALREADY_STALE" ]; then
          echo "[watcher] $ID: PR stale (${AGE_HRS}h >= ${MAX_PR_WAIT_HOURS}h)"
          grava wisp write "$ID" pr_stale "true" 2>/dev/null || true
          grava label "$ID" --add needs-human 2>/dev/null || true
          grava commit -m "watcher: $ID PR stale (>${MAX_PR_WAIT_HOURS}h)" 2>/dev/null || true
        fi
        continue
      fi

      # New comment detection
      COMMENTS_JSON=$(gh api "repos/{owner}/{repo}/pulls/$PR_NUMBER/comments" 2>/dev/null || echo "")
      if [ -z "$COMMENTS_JSON" ]; then continue; fi
      if ! echo "$COMMENTS_JSON" | command -p python3 -c \
          "import json,sys; json.load(sys.stdin)" >/dev/null 2>&1; then
        continue
      fi

      LAST_SEEN=$(grava wisp read "$ID" pr_last_seen_comment_id 2>/dev/null || echo "0")
      [ -n "$LAST_SEEN" ] || LAST_SEEN=0

      NEW_COUNT=$(echo "$COMMENTS_JSON" | command -p python3 -c "
import json, sys
comments = json.load(sys.stdin)
last = int('${LAST_SEEN}' or 0)
new = [c for c in comments if c.get('in_reply_to_id') is None and c.get('id', 0) > last]
print(len(new))
" 2>/dev/null || echo "0")

      REVIEW_DECISION=$(gh pr view "$PR_NUMBER" --json reviewDecision \
        -q '.reviewDecision' 2>/dev/null || echo "")

      if [ "${NEW_COUNT:-0}" -gt 0 ] || [ "$REVIEW_DECISION" = "CHANGES_REQUESTED" ]; then
        HIGHEST=$(echo "$COMMENTS_JSON" | command -p python3 -c "
import json, sys
comments = json.load(sys.stdin)
ids = [c.get('id', 0) for c in comments]
print(max(ids) if ids else 0)
" 2>/dev/null || echo "0")

        NEW_DATA=$(echo "$COMMENTS_JSON" | command -p python3 -c "
import json, sys
comments = json.load(sys.stdin)
last = int('${LAST_SEEN}' or 0)
new = [c for c in comments if c.get('in_reply_to_id') is None and c.get('id', 0) > last]
print(json.dumps(new))
" 2>/dev/null || echo "[]")

        echo "[watcher] $ID: $NEW_COUNT new PR comment(s)"
        grava wisp write "$ID" pr_new_comments "$NEW_DATA" 2>/dev/null || true
        grava wisp write "$ID" pr_last_seen_comment_id "$HIGHEST" 2>/dev/null || true
        grava commit -m "watcher: $ID new PR comments ($NEW_COUNT)" 2>/dev/null || true
      fi
      ;;

    UNKNOWN)
      echo "[watcher] $ID: gh pr view failed (PR #$PR_NUMBER not found or gh not authenticated)"
      ;;

    *)
      echo "[watcher] $ID: unknown PR state '$STATE'"
      ;;
  esac
done
