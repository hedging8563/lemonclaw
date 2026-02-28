#!/usr/bin/env bash
# LemonClaw Smoke Test — 部署后 30 秒验证核心功能
# Usage: ./scripts/smoke-test.sh <instance> [token]
# Example: ./scripts/smoke-test.sh claw-test3 mytoken123
#
# 也可以直接对 URL 测试:
#   ENDPOINT=http://localhost:18789 TOKEN=xxx ./scripts/smoke-test.sh

set -euo pipefail

INSTANCE="${1:-}"
TOKEN="${2:-${TOKEN:-}}"
ENDPOINT="${ENDPOINT:-}"
K8S_HOST="${K8S_HOST:-47.236.26.80}"
TIMEOUT="${TIMEOUT:-60}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass=0; fail=0; skip=0

log_pass() { echo -e "  ${GREEN}✅ PASS${NC}: $1"; ((pass++)); }
log_fail() { echo -e "  ${RED}❌ FAIL${NC}: $1 — $2"; ((fail++)); }
log_skip() { echo -e "  ${YELLOW}⏭ SKIP${NC}: $1 — $2"; ((skip++)); }

# Resolve endpoint
if [[ -z "$ENDPOINT" ]]; then
  if [[ -z "$INSTANCE" ]]; then
    echo "Usage: $0 <instance> [token]"
    echo "   or: ENDPOINT=http://... TOKEN=xxx $0"
    exit 1
  fi
  # Get pod IP via kubectl
  POD_IP=$(ssh -o ConnectTimeout=5 "root@${K8S_HOST}" \
    "kubectl get pod -n claw -l app=${INSTANCE} -o jsonpath='{.items[0].status.podIP}'" 2>/dev/null)
  if [[ -z "$POD_IP" ]]; then
    echo "Error: Cannot find pod for ${INSTANCE}"
    exit 1
  fi
  ENDPOINT="http://${POD_IP}:18789"
  CURL_PREFIX="ssh root@${K8S_HOST}"
  echo "Instance: ${INSTANCE} (${POD_IP})"
else
  CURL_PREFIX=""
  echo "Endpoint: ${ENDPOINT}"
fi

AUTH_HEADER=""
[[ -n "$TOKEN" ]] && AUTH_HEADER="-H 'Authorization: Bearer ${TOKEN}'"

# Helper: run curl (locally or via SSH)
do_curl() {
  local cmd="curl -s --connect-timeout 10 --max-time ${TIMEOUT} $AUTH_HEADER $*"
  if [[ -n "$CURL_PREFIX" ]]; then
    $CURL_PREFIX "$cmd" 2>/dev/null
  else
    eval "$cmd" 2>/dev/null
  fi
}

echo ""
echo "═══════════════════════════════════════════"
echo " LemonClaw Smoke Test"
echo "═══════════════════════════════════════════"
echo ""

# --- Test 1: Health Check ---
echo "1. Health Check"
RESP=$(do_curl "${ENDPOINT}/health")
if echo "$RESP" | grep -q '"status":"ok"'; then
  log_pass "GET /health → ok"
else
  log_fail "GET /health" "got: ${RESP:-empty}"
fi

# --- Test 2: Simple Chat (Chinese) ---
echo "2. Simple Chat (Chinese)"
RESP=$(do_curl -X POST "${ENDPOINT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请用一句话介绍你自己","session":"smoke-zh","timeout":60}')
CONTENT=$(echo "$RESP" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null || echo "")
if [[ -z "$CONTENT" ]]; then
  log_fail "Chinese chat" "empty response: ${RESP:-empty}"
elif echo "$CONTENT" | grep -qP '[\x{4e00}-\x{9fff}]'; then
  log_pass "Chinese chat → got Chinese response"
else
  log_fail "Chinese chat" "response not in Chinese: ${CONTENT:0:100}"
fi

# --- Test 3: /help Command ---
echo "3. /help Command"
RESP=$(do_curl -X POST "${ENDPOINT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"/help","session":"smoke-help","timeout":30}')
CONTENT=$(echo "$RESP" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null || echo "")
if echo "$CONTENT" | grep -qi "lemonclaw"; then
  log_pass "/help → contains LemonClaw"
else
  log_fail "/help" "missing LemonClaw: ${CONTENT:0:100}"
fi

# --- Test 4: /usage Command ---
echo "4. /usage Command"
RESP=$(do_curl -X POST "${ENDPOINT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"/usage","session":"smoke-usage","timeout":30}')
CONTENT=$(echo "$RESP" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null || echo "")
if echo "$CONTENT" | grep -qi "token"; then
  log_pass "/usage → contains token info"
else
  log_fail "/usage" "missing token info: ${CONTENT:0:100}"
fi

# --- Test 5: Anti-Hallucination ---
echo "5. Anti-Hallucination (nanobot)"
RESP=$(do_curl -X POST "${ENDPOINT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"nanobot skill install 命令怎么用","session":"smoke-anti-halluc","timeout":60}')
CONTENT=$(echo "$RESP" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null || echo "")
if [[ -z "$CONTENT" ]]; then
  log_skip "Anti-hallucination" "empty response"
elif echo "$CONTENT" | grep -qi "nanobot skill install"; then
  log_fail "Anti-hallucination" "contains 'nanobot skill install'"
else
  log_pass "Anti-hallucination → no nanobot command suggested"
fi

# --- Test 6: Language Mirroring (English) ---
echo "6. Language Mirroring (English)"
RESP=$(do_curl -X POST "${ENDPOINT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is 1+1? Reply in one word.","session":"smoke-en","timeout":60}')
CONTENT=$(echo "$RESP" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null || echo "")
if [[ -z "$CONTENT" ]]; then
  log_fail "English chat" "empty response"
elif echo "$CONTENT" | grep -qP '[\x{4e00}-\x{9fff}]'; then
  log_fail "English chat" "responded in Chinese: ${CONTENT:0:100}"
else
  log_pass "Language mirroring → English response to English input"
fi

# --- Summary ---
echo ""
echo "═══════════════════════════════════════════"
total=$((pass + fail + skip))
echo -e " Results: ${GREEN}${pass} passed${NC}, ${RED}${fail} failed${NC}, ${YELLOW}${skip} skipped${NC} / ${total} total"
echo "═══════════════════════════════════════════"

[[ $fail -eq 0 ]] && exit 0 || exit 1
