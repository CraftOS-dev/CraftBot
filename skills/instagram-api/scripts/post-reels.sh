#!/bin/bash
# Instagram Graph API — 릴스 포스팅
# 사용법: bash post-reels.sh <영상경로> <캡션파일>
#
# 환경변수 필수:
#   INSTAGRAM_ACCESS_TOKEN        - Meta Graph API 토큰
#   INSTAGRAM_BUSINESS_ACCOUNT_ID - 비즈니스 계정 ID
#   IMGUR_CLIENT_ID               - Imgur Client ID (영상 임시 호스팅)
#
# 참고: 릴스는 동영상 처리에 수분 소요될 수 있습니다.

set -euo pipefail

LOG_DIR="${LOG_DIR:-$HOME/logs/sns}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/instagram-reels.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
err() { log "❌ ERROR: $*"; exit 1; }

# ── 인자 확인 ──────────────────────────────────────────────
VIDEO_PATH="${1:?사용법: $0 <영상경로> <캡션파일>}"
CAPTION_FILE="${2:?사용법: $0 <영상경로> <캡션파일>}"

[[ -f "$VIDEO_PATH" ]]   || err "영상 파일 없음: $VIDEO_PATH"
[[ -f "$CAPTION_FILE" ]] || err "캡션 파일 없음: $CAPTION_FILE"

# ── 환경변수 로드 ──────────────────────────────────────────

TOKEN="${INSTAGRAM_ACCESS_TOKEN:?INSTAGRAM_ACCESS_TOKEN 환경변수 필요}"
IG_ID="${INSTAGRAM_BUSINESS_ACCOUNT_ID:?INSTAGRAM_BUSINESS_ACCOUNT_ID 환경변수 필요}"
IMGUR_ID="${IMGUR_CLIENT_ID:?IMGUR_CLIENT_ID 환경변수 필요}"
API_BASE="https://graph.facebook.com/v21.0"

CAPTION=$(cat "$CAPTION_FILE")
log "🎬 릴스 포스팅 시작: $VIDEO_PATH"

# ── Step 1: 동영상 업로드 (Imgur 비디오) ─────────────────
log "📤 동영상 업로드 중... (시간이 걸릴 수 있습니다)"
# Imgur public upload API (no OAuth required)
VIDEO_URL=$(python3 - "$VIDEO_PATH" "$IMGUR_ID" << 'PYEOF'
import sys, json, urllib.request, urllib.parse
video_path, client_id = sys.argv[1], sys.argv[2]
with open(video_path, "rb") as f:
    video_data = f.read()
boundary = b"----FormBoundary"
body = boundary + b"\r\nContent-Disposition: form-data; name=\"video\"; filename=\"video.mp4\"\r\n\r\n" + video_data + b"\r\n" + boundary + b"--"
req = urllib.request.Request(
    "https://api.imgur.com/3/video",
    data=body,
    headers={"Authorization": f"Client-ID {client_id}", "Content-Type": f"multipart/form-data; boundary={boundary.decode().lstrip('-').strip()}"}
)
with urllib.request.urlopen(req) as resp:
    d = json.load(resp)
print(d.get("data", {}).get("link", ""))
PYEOF
)

[[ -n "$VIDEO_URL" && "$VIDEO_URL" == http* ]] || err "동영상 업로드 실패: $IMGUR_RESP"
log "✅ 업로드 URL: $VIDEO_URL"

# ── Step 2: 릴스 컨테이너 생성 ───────────────────────────
log "🎞️  릴스 컨테이너 생성 중..."
CONTAINER_RESP=$(python3 - "$API_BASE" "$IG_ID" "$VIDEO_URL" "$CAPTION" "$TOKEN" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, ig_id, video_url, caption, token = sys.argv[1:]
params = urllib.parse.urlencode({
    "media_type": "REELS",
    "video_url": video_url,
    "caption": caption,
    "access_token": token
}).encode()
req = urllib.request.Request(f"{api}/{ig_id}/media", data=params, method="POST")
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

# ── Step 3: 처리 상태 대기 ───────────────────────────────
log "⏳ 동영상 처리 대기 중..."
sleep 10

MAX_ATTEMPTS=24  # 최대 2분 대기
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  STATUS_RESP=$(python3 - "$API_BASE" "$CONTAINER_ID" "$TOKEN" << 'PYEOF'
import urllib.request, json, sys

api, container_id, token = sys.argv[1:]
url = f"{api}/{container_id}?fields=status_code,status&access_token={token}"
try:
    resp = urllib.request.urlopen(url)
    print(resp.read().decode())
except Exception as e:
    if hasattr(e, 'read'):
        print(e.read().decode())
    else:
        print(json.dumps({"status_code": "ERROR", "error": str(e)}))
PYEOF
)

  STATUS=$(echo "$STATUS_RESP" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('status_code','IN_PROGRESS'))" 2>/dev/null)

  log "  처리 상태: $STATUS (시도 $attempt/$MAX_ATTEMPTS)"

  if [[ "$STATUS" == "FINISHED" ]]; then
    break
  elif [[ "$STATUS" == "ERROR" ]]; then
    err "동영상 처리 오류: $STATUS_RESP"
  fi

  sleep 5
done

# ── Step 4: 게시 ──────────────────────────────────────────
log "🚀 릴스 게시 중..."
PUBLISH_RESP=$(python3 - "$API_BASE" "$IG_ID" "$CONTAINER_ID" "$TOKEN" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, ig_id, container_id, token = sys.argv[1:]
params = urllib.parse.urlencode({
    "creation_id": container_id,
    "access_token": token
}).encode()
req = urllib.request.Request(f"{api}/{ig_id}/media_publish", data=params, method="POST")
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

MEDIA_ID=$(echo "$PUBLISH_RESP" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
[[ -n "$MEDIA_ID" ]] || err "릴스 게시 실패: $PUBLISH_RESP"

log "✅ 릴스 게시 완료! media_id=$MEDIA_ID"
echo "$MEDIA_ID"
