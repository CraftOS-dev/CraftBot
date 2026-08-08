#!/usr/bin/env bash
# A2APP self-check — exercises every guarantee against a RUNNING app.
#
#   ./a2app-selfcheck.sh <project-dir> [base-url] [--fire]
#
# Creates and deletes its own records; leaves the app as it found it.
# Exits non-zero if any check fails. Safe to re-run.
#
# --fire additionally performs a REAL trigger fire (plus a cooldown check).
# Off by default because queue rows are append-only by design — a test fire
# leaves a rejected row in agent_requests and, on an app connected to a live
# CraftBot, may nudge the agent.
set -uo pipefail

PROJ="${1:?usage: a2app-selfcheck.sh <project-dir> [base-url]}"
PROJ="$(cd "$PROJ" && pwd)"
PORT="$(python3 -c "import json;print(json.load(open('$PROJ/manifest.json'))['port'])")"
BASE="${2:-http://127.0.0.1:$PORT}"
CLI="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools" && pwd)/src/cli.ts"
TOKEN="$(cat "$PROJ/.agent-token" 2>/dev/null || true)"

PASS=0; FAIL=0; CREATED=()

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n     expected: %s\n     got:      %s\n' "$1" "$2" "$3"; FAIL=$((FAIL+1)); }
head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# check <name> <expected-substring> <actual>
check() { case "$3" in *"$2"*) ok "$1";; *) bad "$1" "$2" "${3:0:120}";; esac; }

json()  { python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))" 2>/dev/null; }
code()  { curl -s -m 8 -o /dev/null -w '%{http_code}' "$@"; }
body()  { curl -s -m 8 "$@"; }

W=(-H 'Content-Type: application/json')
[ -n "$TOKEN" ] && W+=(-H "X-LUI-Token: $TOKEN")

head "0. Reachability"
check "app responds"                 '200' "$(code "$BASE/api/health")"
IDENT="$(body "$BASE/api/_a2app")"
check "identity carries a2app marker" '"a2app":true' "$IDENT"
printf '     app=%s adapter=%s schema=%s\n' \
  "$(echo "$IDENT" | json 'protocol')" \
  "$(echo "$IDENT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["adapterVersion"])' 2>/dev/null)" \
  "$(echo "$IDENT" | json 'schemaVersion')"

head "1. Describe (what an external agent reads)"
DESC="$(body "$BASE/api/_a2app/describe")"
check "entities present"             '"entities"'    "$DESC"
check "protocol types, not PB types" '"type":"ref"'  "$(echo "$DESC" | tr -d ' ')"
check "conventions documented"       '"conventions"' "$DESC"
check "day/date fields typed"        'datetime'      "$DESC"

# Pick a writable entity with a required ref, else fall back to any entity.
read -r ENTITY LABELF REFFIELD REFTARGET <<<"$(echo "$DESC" | python3 -c '
import sys,json
d=json.load(sys.stdin)["entities"]
for name,e in d.items():
    if e.get("auth"): continue
    ref=[k for k,f in e["fields"].items() if f.get("type")=="ref" and f.get("required")]
    lab=e.get("label")
    if ref and lab:
        print(name, lab, ref[0], e["fields"][ref[0]]["entity"]); break
else:
    print("", "", "", "")')"

if [ -z "$ENTITY" ]; then
  echo "     (no entity with a required ref — skipping write checks)"
else
  printf '     using entity=%s label=%s ref=%s->%s\n' "$ENTITY" "$LABELF" "$REFFIELD" "$REFTARGET"
  REFVAL="$(body "$BASE/api/collections/$REFTARGET/records?perPage=1" | python3 -c "import sys,json;i=json.load(sys.stdin)['items'];print(i[0]['id'] if i else '')")"

  head "2. Write guard (the original bug)"
  R="$(body -X POST "$BASE/api/collections/$ENTITY/records" "${W[@]}" -d "{\"$LABELF\":\"selfcheck\",\"$REFFIELD\":\"$REFVAL\",\"__nope\":1}")"
  check "unknown field rejected"     'unknown_field' "$R"
  check "rejection is machine-readable" '"code"'     "$R"
  check "all violations listed"      '"violations"'  "$R"

  DATEF="$(echo "$DESC" | python3 -c "
import sys,json
f=json.load(sys.stdin)['entities']['$ENTITY']['fields']
print(next((k for k,v in f.items() if v.get('type')=='datetime' and not v.get('readOnly')), ''))")"
  if [ -n "$DATEF" ]; then
    R="$(body -X POST "$BASE/api/collections/$ENTITY/records" "${W[@]}" -d "{\"$LABELF\":\"selfcheck\",\"$REFFIELD\":\"$REFVAL\",\"$DATEF\":\"tomorrow\"}")"
    check "relative date rejected server-side" 'invalid_date' "$R"
  fi

  head "3. Legitimate writes still work"
  R="$(body -X POST "$BASE/api/collections/$ENTITY/records" "${W[@]}" -d "{\"$LABELF\":\"selfcheck-ok\",\"$REFFIELD\":\"$REFVAL\"}")"
  ID="$(echo "$R" | json 'id')"
  [ -n "$ID" ] && { ok "plain write succeeds"; CREATED+=("$ID"); } || bad "plain write succeeds" "an id" "${R:0:120}"

  head "4. Idempotency"
  K="selfcheck-$RANDOM$RANDOM"
  R1="$(body -X POST "$BASE/api/collections/$ENTITY/records" "${W[@]}" -H "Idempotency-Key: $K" -d "{\"$LABELF\":\"selfcheck-idem\",\"$REFFIELD\":\"$REFVAL\"}")"
  I1="$(echo "$R1" | json 'id')"; [ -n "$I1" ] && CREATED+=("$I1")
  R2="$(body -X POST "$BASE/api/collections/$ENTITY/records" "${W[@]}" -H "Idempotency-Key: $K" -d "{\"$LABELF\":\"selfcheck-idem\",\"$REFFIELD\":\"$REFVAL\"}")"
  check "replay suppressed"          'duplicate_request' "$R2"
  check "replay names the original"  "$I1"               "$R2"

  head "5. Origin guard (the drive-by)"
  H="$(curl -s -m 8 -i "$BASE/api/collections/$ENTITY/records?perPage=1" -H 'Origin: https://evil.example' | tr -d '\r')"
  case "$H" in *"Access-Control-Allow-Origin"*) bad "foreign origin gets no CORS grant" "no ACAO header" "ACAO present";; *) ok "foreign origin gets no CORS grant";; esac
  check "foreign origin cannot write" 'forbidden origin' \
    "$(body -X POST "$BASE/api/collections/$ENTITY/records" -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -d '{}')"
  case "$H" in *"frame-ancestors"*) ok "framing restricted by CSP";; *) bad "framing restricted by CSP" "frame-ancestors" "absent";; esac

  head "6. Agent token"
  if [ -n "$TOKEN" ]; then
    check "write without token refused" 'agent token required' \
      "$(body -X POST "$BASE/api/collections/$ENTITY/records" -H 'Content-Type: application/json' -d "{\"$LABELF\":\"nope\"}")"
    ok "token file present (mode $(stat -f '%OLp' "$PROJ/.agent-token" 2>/dev/null || echo '?'))"
  else
    echo "     (no .agent-token — app not launched since C4; skipping)"
  fi

  head "7. CLI parity"
  check "schema via describe"        "$ENTITY" "$(node "$CLI" data "$PROJ" schema 2>&1)"
  OUT="$(node "$CLI" data "$PROJ" __nosuch create --x 1 2>&1)"
  check "unknown collection named"   'No collection' "$OUT"
fi

head "8. Trigger plane"
check "describe lists triggers"      '"triggers"' "$DESC"
R="$(body -X POST "$BASE/api/collections/agent_requests/records" "${W[@]}" -d '{"trigger":"__selfcheck_nosuch","fired_by":"cli"}')"
check "undeclared trigger rejected"  'undeclared_trigger' "$R"
check "queue is append-only"         'append_only' \
  "$(body -X DELETE "$BASE/api/collections/agent_requests/records/nonexistent0123" "${W[@]}")"

TRIG="$(python3 -c "
import json
try:
    t = json.load(open('$PROJ/triggers.json')).get('triggers', {})
    print(sorted(t.keys())[0] if t else '')
except Exception:
    print('')")"
if [ -n "$TRIG" ]; then
  # The a2app write guard (registered first) rejects the bad enum before the
  # trigger guard sees it — either rejection is correct; match on the field.
  R="$(body -X POST "$BASE/api/collections/agent_requests/records" "${W[@]}" -d "{\"trigger\":\"$TRIG\",\"fired_by\":\"bogus\",\"status\":\"pending\"}")"
  check "invalid fired_by rejected"  '"field":"fired_by"' "$R"

  if [ "${3:-}" = "--fire" ]; then
    PARAMS="$(python3 -c "
import json
spec = json.load(open('$PROJ/triggers.json'))['triggers']['$TRIG'].get('params', {}) or {}
out = {}
for name, p in spec.items():
    if not p.get('required') and 'default' not in p: continue
    if 'default' in p: out[name] = p['default']
    elif p.get('enum'): out[name] = p['enum'][0]
    else: out[name] = {'string': 'selfcheck', 'number': 1, 'boolean': True}[p.get('type', 'string')]
print(json.dumps(out))")"
    R1="$(body -X POST "$BASE/api/collections/agent_requests/records" "${W[@]}" -d "{\"trigger\":\"$TRIG\",\"fired_by\":\"cli\",\"status\":\"pending\",\"params\":$PARAMS}")"
    FID="$(echo "$R1" | json 'id')"
    [ -n "$FID" ] && ok "valid fire lands a pending row" || bad "valid fire lands a pending row" "an id" "${R1:0:120}"
    R2="$(body -X POST "$BASE/api/collections/agent_requests/records" "${W[@]}" -d "{\"trigger\":\"$TRIG\",\"fired_by\":\"cli\",\"status\":\"pending\",\"params\":$PARAMS}")"
    check "cooldown enforced"        'cooldown' "$R2"
    if [ -n "$FID" ]; then
      R3="$(body -X PATCH "$BASE/api/collections/agent_requests/records/$FID" "${W[@]}" -d '{"status":"done"}')"
      check "pending→done refused"   'invalid_transition' "$R3"
      body -X PATCH "$BASE/api/collections/agent_requests/records/$FID" "${W[@]}" \
        -d '{"status":"rejected","error":"a2app-selfcheck test fire"}' -o /dev/null
      printf '     test fire %s left as status=rejected (queue is append-only)\n' "$FID"
    fi
  else
    echo "     (pass --fire to exercise a real fire + cooldown; leaves a rejected row)"
  fi
else
  echo "     (no triggers.json — declared-trigger checks skipped)"
fi

head "9. Attribution log"
if [ -f "$PROJ/logs/agent-actions.jsonl" ]; then
  ok "agent-actions.jsonl exists ($(wc -l < "$PROJ/logs/agent-actions.jsonl" | tr -d ' ') entries)"
else
  bad "agent-actions.jsonl exists" "a log file" "missing"
fi

# ---- cleanup -------------------------------------------------------------
for id in "${CREATED[@]:-}"; do
  [ -n "$id" ] && curl -s -m 8 -X DELETE "$BASE/api/collections/$ENTITY/records/$id" "${W[@]}" -o /dev/null
done
[ ${#CREATED[@]} -gt 0 ] && printf '\n  cleaned up %d test record(s)\n' "${#CREATED[@]}"

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
