#!/bin/bash

# fal.ai Upscale Script
# Usage: ./upscale.sh --image-url URL [--model MODEL] [--scale SCALE]
# Returns: JSON with upscaled image URL

set -e

FAL_API_ENDPOINT="https://fal.run"

# Default values
MODEL="fal-ai/aura-sr"
IMAGE_URL=""
SCALE=4

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
            shift 2
            ;;
        --scale)
            SCALE="$2"
            shift 2
            ;;
        --help|-h)
            echo "fal.ai Upscale Script" >&2
            echo "" >&2
            echo "Usage:" >&2
            echo "  ./upscale.sh --image-url URL [options]" >&2
            echo "" >&2
            echo "Options:" >&2
            echo "  --image-url     Image URL to upscale (required)" >&2
            echo "  --model         Model ID (default: fal-ai/aura-sr)" >&2
            echo "  --scale         Scale factor (default: 4)" >&2
            echo "  --add-fal-key   Setup FAL_KEY in .env" >&2
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

# Validate required inputs
if [ -z "$FAL_KEY" ]; then
    echo "Error: FAL_KEY not set" >&2
    echo "" >&2
    echo "Run: ./upscale.sh --add-fal-key" >&2
    echo "Or:  export FAL_KEY=your_key_here" >&2
    exit 1
fi

if [ -z "$IMAGE_URL" ]; then
    echo "Error: --image-url is required" >&2
    exit 1
fi

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Upscaling with $MODEL..." >&2

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
RESPONSE=$(curl -s -X POST "$FAL_API_ENDPOINT/$MODEL" \
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
