#!/bin/bash
# Instagram Graph API — 캐러셀 포스팅
# 사용법: bash post-carousel.sh <캡션파일> <이미지1> <이미지2> [이미지3...]
#
# 환경변수 필수:
#   INSTAGRAM_ACCESS_TOKEN        - Meta Graph API 토큰
#   INSTAGRAM_BUSINESS_ACCOUNT_ID - 비즈니스 계정 ID
#   IMGUR_CLIENT_ID               - Imgur Client ID (이미지 호스팅)

set -euo pipefail

LOG_DIR="${LOG_DIR:-$HOME/logs/sns}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/instagram-carousel.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
err() { log "❌ ERROR: $*"; exit 1; }

# ── 인자 확인 ──────────────────────────────────────────────
if [[ $# -lt 3 ]]; then
  echo "사용법: $0 <캡션파일> <이미지1> <이미지2> [이미지3...]"
  exit 1
fi

CAPTION_FILE="$1"
shift
IMAGES=("$@")

[[ -f "$CAPTION_FILE" ]] || err "캡션 파일 없음: $CAPTION_FILE"
[[ ${#IMAGES[@]} -ge 2 ]] || err "캐러셀은 최소 2개 이미지 필요"
[[ ${#IMAGES[@]} -le 10 ]] || err "캐러셀은 최대 10개 이미지"

for img in "${IMAGES[@]}"; do
  [[ -f "$img" ]] || err "이미지 파일 없음: $img"
done

# ── 환경변수 로드 ──────────────────────────────────────────

TOKEN="${INSTAGRAM_ACCESS_TOKEN:?INSTAGRAM_ACCESS_TOKEN 환경변수 필요}"
IG_ID="${INSTAGRAM_BUSINESS_ACCOUNT_ID:?INSTAGRAM_BUSINESS_ACCOUNT_ID 환경변수 필요}"
IMGUR_ID="${IMGUR_CLIENT_ID:?IMGUR_CLIENT_ID 환경변수 필요}"
API_BASE="https://graph.facebook.com/v21.0"

CAPTION=$(cat "$CAPTION_FILE")
log "🎠 캐러셀 포스팅 시작: ${#IMAGES[@]}장 이미지"

# ── Step 1: 각 이미지 Imgur 업로드 + 캐러셀 아이템 컨테이너 생성 ──
CONTAINER_IDS=()

for i in "${!IMAGES[@]}"; do
  img="${IMAGES[$i]}"
  log "  [$((i+1))/${#IMAGES[@]}] 업로드: $img"

  # Imgur 업로드 (Python urllib)
  IMGUR_RESP=$(python3 - "${img}" "$IMGUR_ID" << 'PYEOF'
import sys, json, urllib.request, urllib.parse, base64
img_path, client_id = sys.argv[1], sys.argv[2]
with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()
data = urllib.parse.urlencode({"image": img_b64, "type": "base64"}).encode()
req = urllib.request.Request("https://api.imgur.com/3/image", data=data, headers={"Authorization": f"Client-ID {client_id}"})
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
PYEOF
)

  IMG_URL=$(echo "$IMGUR_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('link',''))" 2>/dev/null)

  [[ -n "$IMG_URL" && "$IMG_URL" == http* ]] || err "Imgur 업로드 실패 ($img): $IMGUR_RESP"
  log "  ✅ URL: $IMG_URL"

  ITEM_RESP=$(python3 - "$API_BASE" "$IG_ID" "$IMG_URL" "$TOKEN" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, ig_id, image_url, token = sys.argv[1:]
params = urllib.parse.urlencode({
    "image_url": image_url,
    "is_carousel_item": "true",
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

  ITEM_ID=$(echo "$ITEM_RESP" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [[ -n "$ITEM_ID" ]] || err "캐러셀 아이템 생성 실패: $ITEM_RESP"
  log "  ✅ 아이템 컨테이너: $ITEM_ID"

  CONTAINER_IDS+=("$ITEM_ID")
  sleep 1
done

# ── Step 2: 캐러셀 컨테이너 생성 ─────────────────────────
log "🎠 캐러셀 컨테이너 생성 중..."

# children 파라미터 배열 구성
CHILDREN_JSON=$(python3 - "${CONTAINER_IDS[@]}" << 'PYEOF'
import sys, json
ids = sys.argv[1:]
# URL 인코딩용 children 쌍 출력
for i, cid in enumerate(ids):
    print(f"children[{i}]={cid}")
PYEOF
)

CAROUSEL_RESP=$(python3 - "$API_BASE" "$IG_ID" "$CAPTION" "$TOKEN" "${CONTAINER_IDS[@]}" << 'PYEOF'
import urllib.request, urllib.parse, json, sys

api, ig_id, caption, token = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
children = sys.argv[5:]

params = {
    "media_type": "CAROUSEL",
    "caption": caption,
    "access_token": token,
}
for i, cid in enumerate(children):
    params[f"children[{i}]"] = cid

encoded = urllib.parse.urlencode(params).encode()
req = urllib.request.Request(f"{api}/{ig_id}/media", data=encoded, method="POST")
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

CAROUSEL_ID=$(echo "$CAROUSEL_RESP" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
[[ -n "$CAROUSEL_ID" ]] || err "캐러셀 컨테이너 생성 실패: $CAROUSEL_RESP"
log "✅ 캐러셀 컨테이너: $CAROUSEL_ID"

# ── Step 3: 게시 ──────────────────────────────────────────
log "🚀 캐러셀 게시 중..."
PUBLISH_RESP=$(python3 - "$API_BASE" "$IG_ID" "$CAROUSEL_ID" "$TOKEN" << 'PYEOF'
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
[[ -n "$MEDIA_ID" ]] || err "캐러셀 게시 실패: $PUBLISH_RESP"

log "✅ 캐러셀 게시 완료! media_id=$MEDIA_ID (${#IMAGES[@]}장)"
echo "$MEDIA_ID"
