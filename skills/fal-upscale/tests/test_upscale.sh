#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
UPSCALE_SCRIPT="$SCRIPT_DIR/../scripts/upscale.sh"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

MOCK_CURL="$TEMP_DIR/curl"
CALL_LOG="$TEMP_DIR/calls.log"
POLL_COUNT="$TEMP_DIR/poll-count"

cat > "$MOCK_CURL" <<'EOF'
#!/bin/bash
set -euo pipefail

OUTPUT_FILE=""
METHOD="GET"
URL=""
PAYLOAD=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -w|-H)
            shift 2
            ;;
        -X)
            METHOD="$2"
            shift 2
            ;;
        -d)
            PAYLOAD="$2"
            shift 2
            ;;
        -s|-sS)
            shift
            ;;
        http*)
            URL="$1"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

printf '%s %s %s\n' "$METHOD" "$URL" "$PAYLOAD" >> "$CALL_LOG"

if [[ "$URL" == https://fal.run/* ]]; then
    printf '%s\n' '{"image":{"url":"https://output.test/fal.png"}}'
    exit 0
fi

if [ "$METHOD" = "POST" ]; then
    if [ "${MOCK_POST_STATUS:-200}" = "402" ]; then
        printf '%s\n' '{"code":402,"msg":"insufficient balance"}' > "$OUTPUT_FILE"
        printf '402'
    else
        printf '%s\n' '{"code":200,"data":{"id":"prediction-1","status":"created"}}' > "$OUTPUT_FILE"
        printf '200'
    fi
    exit 0
fi

COUNT=0
[ -f "$POLL_COUNT" ] && COUNT=$(cat "$POLL_COUNT")
COUNT=$((COUNT + 1))
printf '%s' "$COUNT" > "$POLL_COUNT"
if [ "$COUNT" -eq 1 ]; then
    printf '%s\n' '{"code":200,"data":{"id":"prediction-1","status":"processing"}}' > "$OUTPUT_FILE"
else
    printf '%s\n' '{"code":200,"data":{"id":"prediction-1","status":"completed","outputs":["https://output.test/atlas.png"]}}' > "$OUTPUT_FILE"
fi
printf '200'
EOF
chmod +x "$MOCK_CURL"

export CURL_BIN="$MOCK_CURL"
export SLEEP_BIN=true
export CALL_LOG POLL_COUNT

ATLASCLOUD_API_KEY=test-key bash "$UPSCALE_SCRIPT" \
    --provider atlas \
    --image-url 'https://input.test/image.png' \
    --scale 4 \
    --output-format png > "$TEMP_DIR/atlas-output.json"

jq -e '.provider == "atlas" and .model == "atlascloud/image-upscaler" and .image.url == "https://output.test/atlas.png"' \
    "$TEMP_DIR/atlas-output.json" >/dev/null
[ "$(grep -c '^POST .*generateImage' "$CALL_LOG")" -eq 1 ]
[ "$(grep -c '^GET .*prediction/prediction-1' "$CALL_LOG")" -eq 2 ]
PAYLOAD=$(awk '/^POST .*generateImage/ {sub(/^[^ ]+ [^ ]+ /, ""); print}' "$CALL_LOG")
jq -e '.model == "atlascloud/image-upscaler" and .image == "https://input.test/image.png" and .outscale == 4 and .output_format == "png"' \
    <<< "$PAYLOAD" >/dev/null

if bash "$UPSCALE_SCRIPT" --provider atlas --image-url 'https://input.test/image.png' > /dev/null 2>&1; then
    echo "expected missing Atlas credential to fail" >&2
    exit 1
fi

: > "$CALL_LOG"
if MOCK_POST_STATUS=402 ATLASCLOUD_API_KEY=test-key bash "$UPSCALE_SCRIPT" \
    --provider atlas --image-url 'https://input.test/image.png' > /dev/null 2>&1; then
    echo "expected failed Atlas submission to fail" >&2
    exit 1
fi
[ "$(grep -c '^POST .*generateImage' "$CALL_LOG")" -eq 1 ]
if grep -q 'prediction/' "$CALL_LOG"; then
    echo "failed Atlas submission must not start prediction polling" >&2
    exit 1
fi

: > "$CALL_LOG"
FAL_KEY=test-key bash "$UPSCALE_SCRIPT" --image-url 'https://input.test/image.png' > "$TEMP_DIR/fal-output.json"
jq -e '.image.url == "https://output.test/fal.png"' "$TEMP_DIR/fal-output.json" >/dev/null
grep -q '^POST https://fal.run/fal-ai/aura-sr' "$CALL_LOG"

echo "All fal-upscale tests passed"
