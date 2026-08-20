# VLM and media generation

Beyond text, CraftBot uses models to understand images and video, generate images, and generate videos. Each capability has its own provider setting with sensible fallbacks. This page covers which providers support what, which actions use each, and what it costs.

## Vision (VLM)

The VLM answers questions about images. If you don't set `model.vlm_provider`, it **follows your LLM provider**. Set it only when you want a different (usually cheaper) model for vision, or when your LLM provider has no vision model at all.

| Provider | Default VLM model | Notes |
|---|---|---|
| **Anthropic** | `claude-sonnet-4-6` | |
| **OpenAI** | `gpt-5.2-2025-12-11` | |
| **Google Gemini** | `gemini-2.5-pro` | Only provider that analyzes multiple video frames in a single call |
| **BytePlus** | `seed-2-0-pro-260328` | |
| **Ollama (`remote`)** | `llava:7b` | Pull a vision model on your server first |
| **Grok (xAI)** | `grok-4-0709` | Different from the `grok-3` LLM default |
| **Moonshot** | `moonshot-v1-8k-vision-preview` | |
| **MiniMax** | `MiniMax-VL-01` | |
| **Z.ai (GLM)** | `glm-5.2` | |
| **OpenRouter** | `anthropic/claude-sonnet-4.5` | Any vision-capable slug works |
| **AWS Bedrock** | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 accepts image input |

**DeepSeek and Fugu have no vision model.** With one of them as your only provider, vision actions return a clean "VLM not available" error instead of crashing. Set `vlm_provider` to any provider in the table above (its key must also be configured) to restore vision. Override the model with `model.vlm_model`, where `null` means the registry default.

### What uses the VLM

- **`describe_image`**: sends an image plus a prompt to the VLM and returns a markdown-ready description. Used whenever the agent needs to look at a picture, screenshot, or document scan.
- **`understand_video`**: two paths. When a Google API key is configured, the video is uploaded via the Gemini Files API for native understanding with full temporal context (this path runs regardless of your VLM provider, and the uploaded file is deleted from Google's servers after the call). Without a Google key, CraftBot extracts evenly-spaced keyframes with OpenCV and sends them to your configured VLM. Gemini gets all frames in one call, while other providers analyze them frame by frame.

## Image generation

The `generate_image` action turns a text prompt into a PNG. Two providers support it:

| Provider | Default model | Notes |
|---|---|---|
| **OpenAI** | `gpt-image-2` | Three canvas sizes only; 16:9 and 9:16 requests map to the nearest fit (1536×1024 / 1024×1536); tops out at ~1536px regardless of the requested resolution |
| **Google Gemini** | `gemini-3-pro-image` | Native negative prompts; reference images act as style guidance |

Set the provider with `model.image_gen_provider` (default `openai`) and override the model with `model.image_gen_model`. If unset, generation follows your VLM provider when it can generate images, otherwise falls back to OpenAI.

The action accepts aspect ratio, resolution (1K/2K/4K), up to 4 images per call, a negative prompt, and reference images for style consistency across a series. Reference-image semantics differ: Gemini treats them as style guidance, OpenAI as compositional/mask inputs, so results vary between the two.

## Video generation

The `generate_video` action produces an MP4. Three providers support it:

| Provider | Default model | Duration | Notes |
|---|---|---|---|
| **Google Gemini** | `veo-3.1-generate-preview` | 4/6/8 s | Default provider; synchronized audio; 4K is Veo-only; supports last-frame and style reference images |
| **OpenAI** | `sora-2` | 4/8/12 s | Synchronized audio; standard tier tops out at 720p; single reference image |
| **BytePlus** | `seedance-1-0-pro-fast-251015` | 2–12 s | Audio on 2.0+ models only; `camera_fixed` and watermark flags |

Set the provider with `model.video_gen_provider` (default `gemini`) and the model with `model.video_gen_model`. If unset, it follows the image-generation provider when that provider can generate video, else Gemini.

Generation is long-running: the action blocks while it submits, polls, and downloads, typically 60–300 seconds, with a hard cap around 25 minutes. Sora and Veo only support 16:9 and 9:16 aspect ratios; for image-to-video, pass a start frame via `reference_image`.

## Cost notes

- **Vision is token-heavy.** An image costs far more input tokens than the same request in text. If the agent describes images routinely, point `vlm_provider` at a cheaper model than your reasoning LLM. The two settings are independent for exactly this reason.
- **Keep inputs small.** Lower-resolution images cost fewer tokens; for video, fewer keyframes (`max_frames`, default 8) means fewer VLM calls on the fallback path.
- **Image generation bills per image**, scaled by resolution/quality. Batch related images into one call with reference images rather than iterating blind.
- **Video generation is the most expensive capability**, billed per second of output at the chosen resolution. Prototype prompts at 480p/720p and short durations before rendering at 1080p+.
- The Gemini-native `understand_video` path uploads the whole file once instead of sampling frames, which is usually both better *and* cheaper for long videos than many per-frame VLM calls.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "VLM not available" | LLM provider has no vision model (DeepSeek, Fugu) and no `vlm_provider` set | Set `vlm_provider` to a vision-capable provider and configure its key |
| `generate_image` / `generate_video` errors about provider | Configured provider doesn't support that capability | Set `image_gen_provider` to `openai`/`gemini`, `video_gen_provider` to `gemini`/`openai`/`byteplus` |
| Generated image ignores 16:9 | OpenAI has no true 16:9 canvas | Use Gemini for exact wide/tall ratios |
| `understand_video` falls back to keyframes | No Google API key configured | Add a `GOOGLE_API_KEY`; the native path activates even if Gemini isn't your VLM provider |
| Video task appears stuck | Generation blocks by design | Wait; typical runs are 60–300 s, and logs show polling progress |

More cases: [Provider troubleshooting](../../reference/troubleshooting/providers.md).

## Related

- [LLM providers](llm.md): the full provider matrix and key setup
- [settings.json](../configuration/config-json.md): the `model.*` fields these settings live in
- [Quickstart](../../start/quickstart.md): get a text conversation working before adding media
- [Environment variables](../../reference/env-vars.md): key names per provider
