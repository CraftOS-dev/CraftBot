#!/bin/bash
# Threads API — 게시글 포스팅
# 사용법: bash post-threads.sh <캡션파일> [이미지URL]
#
# 환경변수 필수:
#   THREADS_ACCESS_TOKEN - Threads API 토큰
#   THREADS_USER_ID      - Threads 유저 ID
#
# 환경변수 선택:
#   INSTAGRAM_ACCESS_TOKEN        - 대체 토큰 (THREADS_ACCESS_TOKEN 없을 때)

set -euo pipefail

LOG_DIR="${LOG_DIR:-$HOME/logs/sns}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/threads-post.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
err() { log "❌ ERROR: $*"; exit 1; }
if [ -f ~/.openclaw/.env ]; then source ~/.openclaw/.env; fi


# ── 인자 확인 ──────────────────────────────────────────────
CAPTION_FILE="${1:?사용법: $0 <캡션파일> [이미지URL]}"
IMAGE_URL="${2:-}"

[[ -f "$CAPTION_FILE" ]] || err "캡션 파일 없음: $CAPTION_FILE"

# ── 환경변수 로드 ──────────────────────────────────────────

# Threads 전용 토큰 우선, 없으면 Instagram 토큰 사용
TOKEN="${THREADS_ACCESS_TOKEN:-${INSTAGRAM_ACCESS_TOKEN:-}}"
[[ -n "$TOKEN" ]] || err "THREADS_ACCESS_TOKEN 또는 INSTAGRAM_ACCESS_TOKEN 환경변수 필요"

USER_ID="${THREADS_USER_ID:?THREADS_USER_ID 환경변수 필요}"
API_BASE="https://graph.threads.net/v1.0"

CAPTION=$(python3 /Users/tomas/.openclaw/workspace/scripts/utils/clean_md.py --threads < "$CAPTION_FILE")
log "🧵 Threads 포스팅 시작 (캡션 ${#CAPTION}자)"

# ── Step 1: 컨테이너 생성 ─────────────────────────────────
if [[ -n "$IMAGE_URL" ]]; then
  log "🖼️  이미지 컨테이너 생성 중..."
  MEDIA_TYPE="IMAGE"
else
  log "📝 텍스트 컨테이너 생성 중..."
  MEDIA_TYPE="TEXT"
fi

CONTAINER_RESP=$(python3 - "$API_BASE" "$USER_ID" "$MEDIA_TYPE" "$CAPTION" "$TOKEN" "$IMAGE_URL" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, user_id, media_type, caption, token, image_url = sys.argv[1:]

params = {
    "media_type": media_type,
    "text": caption,
    "access_token": token,
}
if image_url:
    params["image_url"] = image_url

encoded = urllib.parse.urlencode(params).encode()
req = urllib.request.Request(f"{api}/{user_id}/threads", data=encoded, method="POST")
try:
    resp = urllib.request.urlopen(req)
    print(resp.read().decode())
except Exception as e:
    if hasattr(e, 'read'):
        print(e.read().decode())
    else:
        print(json.dumps({"error": str(e)}))
PYEOF
)

CONTAINER_ID=$(echo "$CONTAINER_RESP" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
[[ -n "$CONTAINER_ID" ]] || err "컨테이너 생성 실패: $CONTAINER_RESP"
log "✅ 컨테이너: $CONTAINER_ID"

# ── Step 2: 게시 ──────────────────────────────────────────
sleep 2
log "🚀 Threads 게시 중..."

PUBLISH_RESP=$(python3 - "$API_BASE" "$USER_ID" "$CONTAINER_ID" "$TOKEN" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, user_id, container_id, token = sys.argv[1:]
params = urllib.parse.urlencode({
    "creation_id": container_id,
    "access_token": token
}).encode()
req = urllib.request.Request(f"{api}/{user_id}/threads_publish", data=params, method="POST")
try:
    resp = urllib.request.urlopen(req)
    print(resp.read().decode())
except Exception as e:
    if hasattr(e, 'read'):
        print(e.read().decode())
    else:
        print(json.dumps({"error": str(e)}))
PYEOF
)

THREAD_ID=$(echo "$PUBLISH_RESP" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
[[ -n "$THREAD_ID" ]] || err "게시 실패: $PUBLISH_RESP"

log "✅ Threads 게시 완료! thread_id=$THREAD_ID"
echo "$THREAD_ID"
