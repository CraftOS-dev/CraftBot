---
name: fal-upscale
description: Upscale and enhance image resolution using AI. Use when the user requests "Upscale image", "Enhance resolution", "Make image bigger", "Increase quality", or similar upscaling tasks.
metadata:
  author: fal-ai
  version: "1.0.0"
---

# fal.ai Upscale

Upscale and enhance image resolution using state-of-the-art AI models.

## How It Works

1. User provides image URL and optional scale factor
2. Script selects appropriate upscaling model
3. Sends request to fal.ai API
4. Returns upscaled image URL

## Image Upscale Models

| Model | Scale | Best For |
|-------|-------|----------|
| `fal-ai/aura-sr` | 4x | General upscaling, fast |
| `fal-ai/clarity-upscaler` | 2-4x | Detail preservation |
| `fal-ai/creative-upscaler` | 2-4x | Creative enhancement |

## Video Upscale Models

| Model | Notes |
|-------|-------|
| `fal-ai/video-upscaler` | General purpose |
| `fal-ai/topaz/upscale/video` | **Premium quality** |
| `fal-ai/bria/video/increase-resolution` | Fast |
| `fal-ai/flashvsr` | Real-time |
| `fal-ai/seedvr/upscale/video` | High fidelity |
| `fal-ai/bytedance-upscaler` | Good balance |
| `fal-ai/simalabs/sima-video-upscaler-lite` | Lightweight |

## Usage

```bash
bash /mnt/skills/user/fal-upscale/scripts/upscale.sh [options]
```

**Arguments:**
- `--image-url` - URL of image to upscale (required)
- `--model` - Model ID (defaults to `fal-ai/aura-sr`)
- `--scale` - Upscale factor: 2 or 4 (default: 4)

**Examples:**

```bash
# Image upscale with AuraSR (4x, fast)
bash /mnt/skills/user/fal-upscale/scripts/upscale.sh \
  --image-url "https://example.com/image.jpg"

# Image upscale with Clarity (detail preservation)
bash /mnt/skills/user/fal-upscale/scripts/upscale.sh \
  --image-url "https://example.com/image.jpg" \
  --model "fal-ai/clarity-upscaler" \
  --scale 2

# Video upscale (general purpose)
bash /mnt/skills/user/fal-upscale/scripts/upscale.sh \
  --video-url "https://example.com/video.mp4" \
  --model "fal-ai/video-upscaler"

# Video upscale (premium quality)
bash /mnt/skills/user/fal-upscale/scripts/upscale.sh \
  --video-url "https://example.com/video.mp4" \
  --model "fal-ai/topaz/upscale/video"
```

## MCP Tool Alternative

If MCP tools are available, prefer using:
```
mcp__fal-ai__generate({
  modelId: "fal-ai/aura-sr",
  input: {
    image_url: "https://example.com/image.jpg"
  }
})
```

## Output

```
Upscaling with fal-ai/aura-sr...
Upscale complete!

Image URL: https://v3.fal.media/files/abc123/upscaled.png
Original: 512x512
Upscaled: 2048x2048
```

JSON output:
```json
{
  "image": {
    "url": "https://v3.fal.media/files/abc123/upscaled.png",
    "width": 2048,
    "height": 2048
  }
}
```

## Present Results to User

```
Here's your upscaled image:

![Upscaled Image](https://v3.fal.media/files/...)

• 512×512 → 2048×2048 (4x)
```

## Model Selection Guide

**AuraSR** (`fal-ai/aura-sr`)
- Best for: Quick upscaling, general images
- Speed: ~2 seconds
- Fixed 4x scale

**Clarity Upscaler** (`fal-ai/clarity-upscaler`)
- Best for: Preserving fine details
- Speed: ~5 seconds
- Configurable scale (2x or 4x)

**Creative Upscaler** (`fal-ai/creative-upscaler`)
- Best for: Adding artistic detail
- Speed: ~10 seconds
- Enhances while upscaling

## Troubleshooting

### API Key Error
```
Error: FAL_KEY environment variable not set

To fix:
1. Get your API key from https://fal.ai/dashboard/keys
2. Set: export FAL_KEY=your_key_here
```

### Image URL Error
```
Error: Could not fetch image from URL

Make sure:
1. The image URL is publicly accessible
2. The URL points directly to an image file
3. The image format is supported (JPEG, PNG, WebP)
```

### Network Error
```
Network error. To fix on claude.ai:

1. Go to https://claude.ai/settings/capabilities
2. Add *.fal.ai to the allowed domains
3. Try again
```
