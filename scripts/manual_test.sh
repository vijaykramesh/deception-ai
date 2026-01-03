#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1" >&2
    exit 1
  }
}

need curl
need jq

echo "==> Using BASE_URL=$BASE_URL"

echo "==> Healthcheck"
curl -fsS "$BASE_URL/healthcheck" | jq

echo "==> Creating 6-player game (witness + accomplice should be included)"
GAME_JSON="$(curl -fsS -X POST "$BASE_URL/game" \
  -H 'Content-Type: application/json' \
  -d '{"num_ai_players":6,"num_human_players":0}')"

GAME_ID="$(echo "$GAME_JSON" | jq -r '.game_id')"
echo "GAME_ID=$GAME_ID"

MURDERER_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.role=="murderer") | .player_id')"
FS_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.role=="forensic_scientist") | .player_id')"
ACCOMPLICE_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.role=="accomplice") | .player_id')"
WITNESS_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.role=="witness") | .player_id')"

echo "MURDERER_ID=$MURDERER_ID"
echo "FS_ID=$FS_ID"
echo "ACCOMPLICE_ID=$ACCOMPLICE_ID"
echo "WITNESS_ID=$WITNESS_ID"

if [[ -z "$MURDERER_ID" || -z "$FS_ID" || -z "$ACCOMPLICE_ID" || -z "$WITNESS_ID" ]]; then
  echo "ERROR: Did not find all required roles (murderer/fs/accomplice/witness) in created game." >&2
  echo "$GAME_JSON" | jq
  exit 1
fi

CLUE_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.player_id=="'"$MURDERER_ID"'") | .hand.clue_ids[0]')"
MEANS_ID="$(echo "$GAME_JSON" | jq -r '.players[] | select(.player_id=="'"$MURDERER_ID"'") | .hand.means_ids[0]')"

echo "Chosen from murderer's hand:"
echo "  CLUE_ID=$CLUE_ID"
echo "  MEANS_ID=$MEANS_ID"

echo "==> Checking murderer mailbox has prompt_murder_pick"
MBOX_MURDERER="$(curl -fsS "$BASE_URL/games/$GAME_ID/players/$MURDERER_ID/mailbox?count=200")"
PROMPT_COUNT="$(echo "$MBOX_MURDERER" | jq '[.messages[].fields.type | select(.=="prompt_murder_pick")] | length')"
if [[ "$PROMPT_COUNT" -lt 1 ]]; then
  echo "ERROR: murderer mailbox missing prompt_murder_pick" >&2
  echo "$MBOX_MURDERER" | jq
  exit 1
fi
echo "OK: murderer mailbox contains prompt_murder_pick"

# If RUN_AGENT=1, have the server poll AI players once and let the murderer AI pick using the LLM.
if [[ "${RUN_AGENT:-0}" == "1" ]]; then
  echo "==> RUN_AGENT=1: triggering agent runner to poll once (murderer should pick via LLM)"
  curl -fsS -X POST "$BASE_URL/games/$GAME_ID/agents/run_once?block_ms=2000&count=50" | jq
  AFTER_JSON="$(curl -fsS "$BASE_URL/game/$GAME_ID")"
  PHASE="$(echo "$AFTER_JSON" | jq -r '.phase')"

  # In agent mode, the LLM may pick different cards than the first ones we printed above.
  # Update expected IDs from the authoritative game state.
  CLUE_ID="$(echo "$AFTER_JSON" | jq -r '.solution.clue_id')"
  MEANS_ID="$(echo "$AFTER_JSON" | jq -r '.solution.means_id')"
  echo "==> Agent picked solution from LLM: clue=$CLUE_ID means=$MEANS_ID"
else
  echo "==> Submitting murder pick via generic action endpoint (manual)"
  AFTER_JSON="$(curl -fsS -X POST "$BASE_URL/games/$GAME_ID/actions/murder" \
    -H 'Content-Type: application/json' \
    -d "{\"player_id\":\"$MURDERER_ID\",\"clue\":\"$CLUE_ID\",\"means\":\"$MEANS_ID\"}")"
  PHASE="$(echo "$AFTER_JSON" | jq -r '.phase')"
fi

if [[ "$PHASE" != "discussion" ]]; then
  echo "ERROR: expected phase=discussion after murder pick, got: $PHASE" >&2
  echo "$AFTER_JSON" | jq
  exit 1
fi
echo "OK: game phase is now discussion"

echo "==> Checking witness mailbox for witness_identities_revealed (should NOT include clue/means)"
MBOX_WITNESS="$(curl -fsS "$BASE_URL/games/$GAME_ID/players/$WITNESS_ID/mailbox?count=200")"
WITNESS_REVEAL="$(echo "$MBOX_WITNESS" | jq '[.messages[].fields | select(.type=="witness_identities_revealed")] | last')"
if [[ "$WITNESS_REVEAL" == "null" ]]; then
  echo "ERROR: witness mailbox missing witness_identities_revealed" >&2
  echo "$MBOX_WITNESS" | jq
  exit 1
fi

WITNESS_MURDERER_ID="$(echo "$WITNESS_REVEAL" | jq -r '.murderer_id')"
WITNESS_ACCOMPLICE_ID="$(echo "$WITNESS_REVEAL" | jq -r '.accomplice_id')"

if [[ "$WITNESS_MURDERER_ID" != "$MURDERER_ID" ]]; then
  echo "ERROR: witness reveal murderer_id mismatch: expected $MURDERER_ID got $WITNESS_MURDERER_ID" >&2
  echo "$WITNESS_REVEAL" | jq
  exit 1
fi
if [[ "$WITNESS_ACCOMPLICE_ID" != "$ACCOMPLICE_ID" ]]; then
  echo "ERROR: witness reveal accomplice_id mismatch: expected $ACCOMPLICE_ID got $WITNESS_ACCOMPLICE_ID" >&2
  echo "$WITNESS_REVEAL" | jq
  exit 1
fi

# Ensure witness reveal does NOT contain clue/means fields
HAS_CLUE_FIELD="$(echo "$WITNESS_REVEAL" | jq 'has("clue_id") or has("means_id")')"
if [[ "$HAS_CLUE_FIELD" != "false" ]]; then
  echo "ERROR: witness reveal unexpectedly contains clue_id/means_id" >&2
  echo "$WITNESS_REVEAL" | jq
  exit 1
fi
echo "OK: witness got identities only (no clue/means)"

echo "==> Checking murderer/fs/accomplice mailboxes for murder_solution_chosen"
check_solution_chosen() {
  local pid="$1"
  local who="$2"
  local mbox
  local last
  mbox="$(curl -fsS "$BASE_URL/games/$GAME_ID/players/$pid/mailbox?count=200")"
  last="$(echo "$mbox" | jq '[.messages[].fields | select(.type=="murder_solution_chosen")] | last')"
  if [[ "$last" == "null" ]]; then
    echo "ERROR: $who mailbox missing murder_solution_chosen" >&2
    echo "$mbox" | jq
    exit 1
  fi
  local got_clue got_means
  got_clue="$(echo "$last" | jq -r '.clue_id')"
  got_means="$(echo "$last" | jq -r '.means_id')"
  if [[ "$got_clue" != "$CLUE_ID" || "$got_means" != "$MEANS_ID" ]]; then
    echo "ERROR: $who solution mismatch: expected ($CLUE_ID,$MEANS_ID) got ($got_clue,$got_means)" >&2
    echo "Tip: if RUN_AGENT=1, ensure /game/{id} returned a non-null solution."
    echo "$last" | jq
    exit 1
  fi
  echo "OK: $who got murder_solution_chosen with chosen IDs"
}

check_solution_chosen "$MURDERER_ID" "murderer"
check_solution_chosen "$FS_ID" "forensic_scientist"
check_solution_chosen "$ACCOMPLICE_ID" "accomplice"

echo
echo "================ SUMMARY ================"
echo "GAME_ID=$GAME_ID"
echo "phase=$PHASE"
echo "murderer=$MURDERER_ID"
echo "forensic_scientist=$FS_ID"
echo "accomplice=$ACCOMPLICE_ID"
echo "witness=$WITNESS_ID"
echo "solution: clue=$CLUE_ID means=$MEANS_ID"
echo "========================================="
echo "PASS"
