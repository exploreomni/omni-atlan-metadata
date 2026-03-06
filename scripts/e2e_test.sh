#!/usr/bin/env bash
# End-to-end local test script.
# Reads credentials from .env (or existing env), then:
#   1. Tests auth
#   2. Runs preflight check
#   3. Triggers workflow (max_pages=1 for speed)
#   4. Polls status until complete
#   5. Prints entity count from output file

set -euo pipefail

# ---- load .env if present ---------------------------------------------------
if [ -f "$(dirname "$0")/../.env" ]; then
  export $(grep -v '^#' "$(dirname "$0")/../.env" | xargs)
fi

BASE_URL="${OMNI_BASE_URL:?Set OMNI_BASE_URL in .env}"
TOKEN="${OMNI_API_TOKEN:?Set OMNI_API_TOKEN in .env}"
APP="${APP_URL:-http://localhost:8000}"
PAGE_SIZE="${PAGE_SIZE:-10}"
MAX_PAGES="${MAX_PAGES:-1}"
OUTPUT_FILE="${OUTPUT_FILE:-omni_entities.ndjson}"

echo "=== 1. Test auth ==="
curl -sf -X POST "$APP/workflows/v1/auth" \
  -H 'Content-Type: application/json' \
  -d "{\"omni_base_url\":\"$BASE_URL\",\"omni_api_token\":\"$TOKEN\"}" \
  | python3 -m json.tool
echo

echo "=== 2. Preflight check ==="
curl -sf -X POST "$APP/workflows/v1/check" \
  -H 'Content-Type: application/json' \
  -d "{
    \"credentials\": {\"omni_base_url\":\"$BASE_URL\",\"omni_api_token\":\"$TOKEN\"},
    \"metadata\": {\"page_size\": $PAGE_SIZE}
  }" | python3 -m json.tool
echo

echo "=== 3. Trigger workflow (max_pages=$MAX_PAGES) ==="
RESPONSE=$(curl -sf -X POST "$APP/workflows/v1/start" \
  -H 'Content-Type: application/json' \
  -d "{
    \"payload\": {
      \"omni_base_url\": \"$BASE_URL\",
      \"omni_api_token\": \"$TOKEN\",
      \"tenant_id\": \"omni\",
      \"page_size\": $PAGE_SIZE,
      \"max_pages\": $MAX_PAGES,
      \"save_output_local\": true,
      \"output_file\": \"$OUTPUT_FILE\"
    }
  }")
echo "$RESPONSE" | python3 -m json.tool
WORKFLOW_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['workflow_id'])")
RUN_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['run_id'])")
echo "workflow_id=$WORKFLOW_ID  run_id=$RUN_ID"
echo

echo "=== 4. Polling status ==="
for i in $(seq 1 30); do
  STATUS=$(curl -sf "$APP/workflows/v1/status/$WORKFLOW_ID/$RUN_ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('status','unknown'))")
  echo "  [$i] $STATUS"
  if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "completed" ]]; then
    echo "  Done!"
    break
  fi
  if [[ "$STATUS" == "FAILED" || "$STATUS" == "failed" || "$STATUS" == "TERMINATED" ]]; then
    echo "  Workflow failed. Check Temporal UI at http://localhost:8233"
    exit 1
  fi
  sleep 3
done
echo

echo "=== 5. Output sample ==="
if [ -f "$OUTPUT_FILE" ]; then
  ENTITY_COUNT=$(wc -l < "$OUTPUT_FILE" | tr -d ' ')
  echo "Entities written: $ENTITY_COUNT"
  echo
  echo "Type breakdown:"
  python3 -c "
import json, collections
counts = collections.Counter()
with open('$OUTPUT_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            counts[json.loads(line)['typeName']] += 1
for t, n in sorted(counts.items()):
    print(f'  {t}: {n}')
"
  echo
  echo "First entity:"
  head -1 "$OUTPUT_FILE" | python3 -m json.tool
else
  echo "Output file not found: $OUTPUT_FILE"
fi
