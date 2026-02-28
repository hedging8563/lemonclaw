#!/usr/bin/env bash
# LemonClaw Smoke Test
# Usage: TOKEN=xxx ./scripts/smoke-test.sh <instance>

INSTANCE="${1:-}"
TOKEN="${2:-${TOKEN:-}}"
HOST="${K8S_HOST:-47.236.26.80}"
T="${CHAT_TIMEOUT:-30}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
pass=0; fail=0; skip=0
ok()   { echo -e "  ${GREEN}PASS${NC}: $1"; ((pass++)) || true; }
ng()   { echo -e "  ${RED}FAIL${NC}: $1 -- $2"; ((fail++)) || true; }
sk()   { echo -e "  ${YELLOW}SKIP${NC}: $1 -- $2"; ((skip++)) || true; }

[[ -z "$INSTANCE" ]] && { echo "Usage: TOKEN=xxx $0 <instance>"; exit 1; }

POD=$(ssh -o ConnectTimeout=5 root@${HOST} \
  "kubectl get pod -n claw -l app=${INSTANCE} -o jsonpath='{.items[0].metadata.name}'" 2>/dev/null)
[[ -z "$POD" ]] && { echo "Error: pod not found"; exit 1; }

echo "Pod: $POD"

# Build the kubectl exec prefix
K="ssh root@${HOST} kubectl exec ${POD} -n claw --"
AUTH=""
[[ -n "$TOKEN" ]] && AUTH="-H 'Authorization: Bearer ${TOKEN}'"

# chat helper: chat "message" "session"
chat_raw() {
  $K curl -s --max-time $T -X POST http://localhost:18789/api/chat \
    -H "'Content-Type: application/json'" $AUTH \
    -d "'$(printf '{"message":"%s","session":"%s","timeout":%d}' "$1" "$2" "$T")'" 2>/dev/null
}
chat() { chat_raw "$1" "$2" | python3 -c "import sys,json;print(json.loads(sys.stdin.read()).get('response',''))" 2>/dev/null; }

echo ""
echo "======= LemonClaw Smoke Test ======="
echo ""

# 1
echo "1. Health"
R=$($K curl -s http://localhost:18789/health 2>/dev/null)
echo "$R" | grep -q '"ok"' && ok "health" || ng "health" "$R"

# 2
echo "2. /help"
C=$(chat "/help" "s-help")
echo "$C" | grep -qi "lemonclaw" && ok "/help" || ng "/help" "${C:0:60}"

# 3
echo "3. /usage"
C=$(chat "/usage" "s-usage")
echo "$C" | grep -qi "token" && ok "/usage" || ng "/usage" "${C:0:60}"

# 4
echo "4. Chinese"
C=$(chat "你好" "s-zh")
if [[ -z "$C" ]]; then ng "Chinese" "empty"
elif python3 -c "exit(0 if any('\u4e00'<=c<='\u9fff' for c in '''$C''') else 1)" 2>/dev/null; then ok "Chinese (${#C}c)"
else ng "Chinese" "${C:0:60}"; fi

# 5
echo "5. English"
C=$(chat "What is 1+1? One word." "s-en")
if [[ -z "$C" ]]; then ng "English" "empty"
elif python3 -c "exit(1 if any('\u4e00'<=c<='\u9fff' for c in '''$C''') else 0)" 2>/dev/null; then ok "English"
else ng "English" "${C:0:60}"; fi

# 6 (last - may trigger tool calls)
echo "6. Anti-hallucination"
C=$(chat "nanobot skill install怎么用" "s-ah")
if [[ -z "$C" ]]; then sk "anti-halluc" "empty"
elif echo "$C" | grep -qi "nanobot skill install"; then ng "anti-halluc" "nanobot cmd"
else ok "anti-halluc"; fi

echo ""
echo "======= ${pass}P ${fail}F ${skip}S / $((pass+fail+skip)) ======="
[[ $fail -eq 0 ]]
