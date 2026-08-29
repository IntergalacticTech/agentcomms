#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# One-command smoke test of the live AgentComms deployment.
# Exercises all the Phase 1-3 endpoints against either the clean
# (api.agentcomms.dev) or direct execute-api URL.
#
# Usage:
#   AGENTCOMMS_API_KEY=ak_live_... ./tools/smoke_test_live.sh
#
# Env overrides:
#   AGENTCOMMS_BASE_URL    — defaults to https://api.agentcomms.dev/v1
#   DOMAIN_FOR_PROVISION   — defaults to agentcomms.dev (the platform pool)

set -uo pipefail

API="${AGENTCOMMS_BASE_URL:-https://api.agentcomms.dev/v1}"
KEY="${AGENTCOMMS_API_KEY:?Set AGENTCOMMS_API_KEY}"
DOMAIN="${DOMAIN_FOR_PROVISION:-agentcomms.dev}"
AUTH=( -H "Authorization: Bearer $KEY" )

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
gray()  { printf "\033[2m%s\033[0m\n" "$1"; }

pass=0
fail=0

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    green "  ✓ $name  (HTTP $actual)"
    pass=$((pass + 1))
  else
    red "  ✗ $name  (expected HTTP $expected, got $actual)"
    fail=$((fail + 1))
  fi
}

echo
gray "API: $API"
gray "Key: ${KEY:0:14}..."
echo

# --- 1. Basic auth surface ---
echo "[1/7] Auth surface"
code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "$API/agents")
check "no-auth request rejected" "401" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" -H "Authorization: Bearer badkey" "$API/agents")
# The authorizer returns Unauthorized for unknown keys; API Gateway renders that as 401.
check "bad-key request rejected" "401" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/agents")
check "valid key GET /agents" "200" "$code"

# --- 2. Agent CRUD ---
echo
echo "[2/7] Agent lifecycle"
TS=$(date +%s)
create_resp=$(curl -sS --max-time 15 -w "|%{http_code}" -X POST "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"smoke-$TS\",\"provision\":{\"email\":{\"local_part\":\"smoke-$TS\",\"domain\":\"$DOMAIN\"}}}" \
  "$API/agents")
create_code="${create_resp##*|}"
create_body="${create_resp%|*}"
check "POST /agents with email provision" "201" "$create_code"
AGENT_ID=$(printf "%s" "$create_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null)
gray "  agent_id=$AGENT_ID"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/agents/$AGENT_ID")
check "GET /agents/{id}" "200" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/agents/$AGENT_ID/channels")
check "GET /agents/{id}/channels" "200" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/agents/$AGENT_ID/messages")
check "GET /agents/{id}/messages (empty inbox)" "200" "$code"

# --- 3. Vault ---
echo
echo "[3/7] Vault (KMS + TOTP)"
vault_resp=$(curl -sS --max-time 10 -w "|%{http_code}" -X POST "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d '{"type":"totp","label":"smoke-test","seed":"JBSWY3DPEHPK3PXP"}' \
  "$API/vault")
vault_code="${vault_resp##*|}"
vault_body="${vault_resp%|*}"
check "POST /vault (TOTP)" "201" "$vault_code"
VAULT_ID=$(printf "%s" "$vault_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('vault_id',''))" 2>/dev/null)
gray "  vault_id=$VAULT_ID"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/vault/$VAULT_ID/totp")
check "GET /vault/{id}/totp (generated code)" "200" "$code"

# --- 4. Personas ---
echo
echo "[4/7] Personas"
persona_resp=$(curl -sS --max-time 10 -w "|%{http_code}" -X POST "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Tester","email":"smoke@example.com"}' \
  "$API/personas")
persona_code="${persona_resp##*|}"
check "POST /personas" "201" "$persona_code"

# --- 5. Domains ---
echo
echo "[5/7] Domains"
domain_resp=$(curl -sS --max-time 15 -w "|%{http_code}" -X POST "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"domain_name\":\"smoke-test-$TS.example\"}" \
  "$API/domains")
domain_code="${domain_resp##*|}"
check "POST /domains (SES DKIM tokens issued)" "201" "$domain_code"

# --- 6. Phase 3 webhook routes ---
echo
echo "[6/7] Webhook routes (auth gates)"
base_no_v1="${API%/v1}"
code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" -X POST "$base_no_v1/webhooks/slack/events")
check "Slack events rejects missing signature" "400" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" -X POST "$base_no_v1/webhooks/telegram/abc123")
check "Telegram webhook ack" "200" "$code"

# --- 7. Cleanup ---
echo
echo "[7/7] Cleanup"
code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" -X DELETE "${AUTH[@]}" "$API/agents/$AGENT_ID")
check "DELETE /agents/{id}" "204" "$code"

code=$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" -X DELETE "${AUTH[@]}" "$API/vault/$VAULT_ID")
check "DELETE /vault/{id}" "204" "$code"

echo
if [ $fail -eq 0 ]; then
  green "SMOKE TEST PASSED: $pass / $((pass + fail))"
else
  red "SMOKE TEST FAILED: $fail of $((pass + fail)) checks failed"
  exit 1
fi
