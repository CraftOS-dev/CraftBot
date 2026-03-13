#!/bin/bash
# Instagram Graph API — 스토리 포스팅
# 사용법: bash post-story.sh <이미지경로>

set -euo pipefail
LOG_DIR="${LOG_DIR:-$HOME/logs/sns}"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/instagram-story.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
err() { log "❌ ERROR: $*"; exit 1; }

IMAGE_PATH="${1:?사용법: $0 <이미지경로>}"
[[ -f "$IMAGE_PATH" ]] || err "이미지 파일 없음: $IMAGE_PATH"


TOKEN="${INSTAGRAM_ACCESS_TOKEN:?INSTAGRAM_ACCESS_TOKEN 환경변수 필요}"
IG_ID="${INSTAGRAM_BUSINESS_ACCOUNT_ID:?INSTAGRAM_BUSINESS_ACCOUNT_ID 환경변수 필요}"
IMGUR_ID="${IMGUR_CLIENT_ID:?IMGUR_CLIENT_ID 환경변수 필요}"
API_BASE="https://graph.facebook.com/v21.0"

log "📤 스토리 업로드 시작: $IMAGE_PATH"

# Imgur 업로드 (Python urllib)
IMAGE_URL=$(python3 - "$IMAGE_PATH" "$IMGUR_ID" << 'PYEOF'
import sys, json, urllib.request, urllib.parse, base64
img_path, client_id = sys.argv[1], sys.argv[2]
with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()
data = urllib.parse.urlencode({"image": img_b64, "type": "base64"}).encode()
req = urllib.request.Request(
    "https://api.imgur.com/3/image",
    data=data,
    headers={"Authorization": f"Client-ID {client_id}"}
)
with urllib.request.urlopen(req) as resp:
    d = json.load(resp)
print(d.get("data", {}).get("link", ""))
PYEOF
)

[[ -n "$IMAGE_URL" && "$IMAGE_URL" == http* ]] || err "Imgur 업로드 실패"
log "✅ Imgur URL: $IMAGE_URL"

# 스토리 게시
python3 - "$API_BASE" "$IG_ID" "$IMAGE_URL" "$TOKEN" << 'PYEOF'
import urllib.request, urllib.parse, json, sys
api, ig_id, image_url, token = sys.argv[1:]

params = urllib.parse.urlencode({
    "image_url": image_url, "media_type": "STORIES", "access_token": token
}).encode()
req = urllib.request.Request(f"{api}/{ig_id}/media", data=params)
with urllib.request.urlopen(req) as resp:
    container_id = json.load(resp)["id"]

params = urllib.parse.urlencode({
    "creation_id": container_id, "access_token": token
}).encode()
req = urllib.request.Request(f"{api}/{ig_id}/media_publish", data=params)
with urllib.request.urlopen(req) as resp:
    result = json.load(resp)
print(f"✅ 스토리 게시 완료: {result.get('id', 'unknown')}")
PYEOF
