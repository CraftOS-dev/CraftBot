#!/bin/bash

# Image Upscale Script
# Usage: ./upscale.sh --image-url URL [--provider fal|atlas] [options]
# Returns: JSON with upscaled image URL

set -e

FAL_API_ENDPOINT="https://fal.run"
ATLAS_API_ENDPOINT="${ATLAS_API_ENDPOINT:-https://api.atlascloud.ai/api/v1}"
CURL_BIN="${CURL_BIN:-curl}"
SLEEP_BIN="${SLEEP_BIN:-sleep}"

# Default values
PROVIDER="fal"
MODEL="fal-ai/aura-sr"
MODEL_SET=false
IMAGE_URL=""
SCALE=4
OUTPUT_FORMAT="png"

# Check for --add-fal-key first
for arg in "$@"; do
    if [ "$arg" = "--add-fal-key" ]; then
        shift
        KEY_VALUE=""
        if [[ -n "$1" && ! "$1" =~ ^-- ]]; then
            KEY_VALUE="$1"
        fi
        if [ -z "$KEY_VALUE" ]; then
            echo "Enter your fal.ai API key:" >&2
            read -r KEY_VALUE
        fi
        if [ -n "$KEY_VALUE" ]; then
            grep -v "^FAL_KEY=" .env > .env.tmp 2>/dev/null || true
            mv .env.tmp .env 2>/dev/null || true
            echo "FAL_KEY=$KEY_VALUE" >> .env
            echo "FAL_KEY saved to .env" >&2
        fi
        exit 0
    fi
done

# Load .env if exists
if [ -f ".env" ]; then
    source .env 2>/dev/null || true
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --image-url)
            IMAGE_URL="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            MODEL_SET=true
            shift 2
            ;;
        --provider)
            PROVIDER="$2"
            shift 2
            ;;
        --scale)
            SCALE="$2"
            shift 2
            ;;
        --output-format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Image Upscale Script" >&2
            echo "" >&2
            echo "Usage:" >&2
            echo "  ./upscale.sh --image-url URL [options]" >&2
            echo "" >&2
            echo "Options:" >&2
            echo "  --image-url     Image URL to upscale (required)" >&2
            echo "  --provider      Provider: fal or atlas (default: fal)" >&2
            echo "  --model         Provider model ID" >&2
            echo "  --scale         Scale factor (default: 4)" >&2
            echo "  --output-format Atlas output format: jpeg, png, webp, or jpg" >&2
            echo "  --add-fal-key   Setup FAL_KEY in .env" >&2
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "$IMAGE_URL" ]; then
    echo "Error: --image-url is required" >&2
    exit 1
fi

if [[ "$PROVIDER" != "fal" && "$PROVIDER" != "atlas" ]]; then
    echo "Error: --provider must be fal or atlas" >&2
    exit 1
fi

if [ "$PROVIDER" = "fal" ] && [ -z "$FAL_KEY" ]; then
    echo "Error: FAL_KEY not set" >&2
    echo "" >&2
    echo "Run: ./upscale.sh --add-fal-key" >&2
    echo "Or:  export FAL_KEY=your_key_here" >&2
    exit 1
fi

if [ "$PROVIDER" = "atlas" ]; then
    if [ -z "$ATLASCLOUD_API_KEY" ]; then
        echo "Error: ATLASCLOUD_API_KEY not set" >&2
        echo "Get a key at https://www.atlascloud.ai/ and export it before running." >&2
        exit 1
    fi
    if ! command -v jq >/dev/null 2>&1; then
        echo "Error: jq is required for the Atlas provider" >&2
        exit 1
    fi
    if [ "$MODEL_SET" = false ]; then
        MODEL="atlascloud/image-upscaler"
    elif [ "$MODEL" != "atlascloud/image-upscaler" ]; then
        echo "Error: Atlas currently supports atlascloud/image-upscaler only" >&2
        exit 1
    fi
    if [[ ! "$SCALE" =~ ^[1-4]([.]0)?$ ]]; then
        echo "Error: Atlas --scale must be between 1 and 4" >&2
        exit 1
    fi
    case "$OUTPUT_FORMAT" in
        jpeg|png|webp|jpg) ;;
        *)
            echo "Error: --output-format must be jpeg, png, webp, or jpg" >&2
            exit 1
            ;;
    esac
fi

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Upscaling with $MODEL..." >&2

if [ "$PROVIDER" = "atlas" ]; then
    PAYLOAD=$(jq -nc \
        --arg model "$MODEL" \
        --arg image "$IMAGE_URL" \
        --argjson outscale "$SCALE" \
        --arg output_format "$OUTPUT_FORMAT" \
        '{model:$model,image:$image,outscale:$outscale,output_format:$output_format}')

    RESPONSE_FILE="$TEMP_DIR/atlas-submit.json"
    HTTP_STATUS=$("$CURL_BIN" -sS -o "$RESPONSE_FILE" -w "%{http_code}" \
        -X POST "$ATLAS_API_ENDPOINT/model/generateImage" \
        -H "Authorization: Bearer $ATLASCLOUD_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD")
    API_CODE=$(jq -r '.code // 200' "$RESPONSE_FILE" 2>/dev/null || echo "invalid")

    if [[ ! "$HTTP_STATUS" =~ ^2 ]] || [ "$API_CODE" != "200" ]; then
        ERROR_MSG=$(jq -r '.msg // .message // .error // empty' "$RESPONSE_FILE" 2>/dev/null)
        echo "Error: Atlas submission failed: ${ERROR_MSG:-HTTP $HTTP_STATUS}" >&2
        exit 1
    fi

    PREDICTION_ID=$(jq -r '.data.id // .id // empty' "$RESPONSE_FILE")
    if [ -z "$PREDICTION_ID" ]; then
        echo "Error: Atlas submission returned no prediction ID" >&2
        exit 1
    fi

    MAX_POLLS="${ATLAS_MAX_POLLS:-30}"
    POLL_DELAY="${ATLAS_POLL_INTERVAL:-2}"
    MAX_DELAY="${ATLAS_MAX_POLL_INTERVAL:-10}"
    POLL_FILE="$TEMP_DIR/atlas-poll.json"

    for ((attempt = 1; attempt <= MAX_POLLS; attempt++)); do
        "$SLEEP_BIN" "$POLL_DELAY"
        HTTP_STATUS=$("$CURL_BIN" -sS -o "$POLL_FILE" -w "%{http_code}" \
            "$ATLAS_API_ENDPOINT/model/prediction/$PREDICTION_ID" \
            -H "Authorization: Bearer $ATLASCLOUD_API_KEY")
        API_CODE=$(jq -r '.code // 200' "$POLL_FILE" 2>/dev/null || echo "invalid")

        if [[ "$HTTP_STATUS" =~ ^2 ]] && [ "$API_CODE" = "200" ]; then
            STATUS=$(jq -r '(.data.status // .status // "") | ascii_downcase' "$POLL_FILE")
            if [[ "$STATUS" == "completed" || "$STATUS" == "succeeded" ]]; then
                OUTPUT_URL=$(jq -r '.data.outputs[0] // .outputs[0] // .data.output[0] // .output[0] // empty' "$POLL_FILE")
                if [ -z "$OUTPUT_URL" ]; then
                    echo "Error: Atlas prediction returned no output URL" >&2
                    exit 1
                fi
                echo "Upscale complete!" >&2
                echo "" >&2
                echo "Image URL: $OUTPUT_URL" >&2
                jq -nc --arg url "$OUTPUT_URL" --arg model "$MODEL" \
                    '{image:{url:$url},model:$model,provider:"atlas"}'
                exit 0
            fi
            if [ "$STATUS" = "failed" ]; then
                ERROR_MSG=$(jq -r '.data.error // .error // "unknown error"' "$POLL_FILE")
                echo "Error: Atlas prediction failed: $ERROR_MSG" >&2
                exit 1
            fi
        fi

        if (( POLL_DELAY < MAX_DELAY )); then
            POLL_DELAY=$((POLL_DELAY * 2))
            if (( POLL_DELAY > MAX_DELAY )); then
                POLL_DELAY="$MAX_DELAY"
            fi
        fi
    done

    echo "Error: Atlas prediction timed out after $MAX_POLLS checks" >&2
    exit 1
fi

# Build payload based on model
if [[ "$MODEL" == *"aura-sr"* ]]; then
    # AuraSR has fixed 4x scale
    PAYLOAD=$(cat <<EOF
{
  "image_url": "$IMAGE_URL"
}
EOF
)
else
    # Other models support scale parameter
    PAYLOAD=$(cat <<EOF
{
  "image_url": "$IMAGE_URL",
  "scale": $SCALE
}
EOF
)
fi

# Make API request
RESPONSE=$("$CURL_BIN" -s -X POST "$FAL_API_ENDPOINT/$MODEL" \
    -H "Authorization: Key $FAL_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

# Check for errors
if echo "$RESPONSE" | grep -q '"error"'; then
    ERROR_MSG=$(echo "$RESPONSE" | grep -o '"message":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -z "$ERROR_MSG" ]; then
        ERROR_MSG=$(echo "$RESPONSE" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
    fi
    echo "Error: $ERROR_MSG" >&2
    exit 1
fi

echo "Upscale complete!" >&2
echo "" >&2

# Extract and display result
OUTPUT_URL=$(echo "$RESPONSE" | grep -o '"url":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "Image URL: $OUTPUT_URL" >&2

# Output JSON for programmatic use
echo "$RESPONSE"
