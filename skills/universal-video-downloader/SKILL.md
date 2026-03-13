---
name: universal-video-downloader
description: Download videos from YouTube, Instagram, TikTok, Twitter/X, and 1000+ other sites using yt-dlp. Supports quality selection and automatic cleanup. Use when a user provides a video link from any platform and wants to download it.
metadata: {"openclaw":{"emoji":"🎥","requires":{"bins":["yt-dlp","ffmpeg"]}}}
---

# Universal Video Downloader

Download videos from almost any platform using the powerful `yt-dlp` tool.

## Features
-   **Platform Support:** YouTube, Instagram, TikTok, Twitter/X, Facebook, and many more.
-   **Quality Selection:** Choose from 144p up to 4K/8K resolutions.
-   **Automatic Cleanup:** Files are deleted from the server immediately after successful upload to the chat.
-   **Smart Merging:** Automatically merges high-quality video and audio streams into a single MP4 file.

## Workflow
1.  **Trigger:** User sends a video link (e.g., YouTube, Instagram).
2.  **Information Gathering:** The agent uses `scripts/download.py info` to fetch available qualities and the video title.
3.  **User Choice:** The agent presents resolutions to the user and asks which one they prefer.
4.  **Download:** Once selected, the agent runs `scripts/download.py download` with the specific Format ID.
5.  **Delivery:** The agent sends the resulting file using the `message` tool with `filePath`.
6.  **Cleanup:** The agent **must** delete the file from disk using `rm` immediately after the message is successfully sent to save disk space.

## Usage for Agents

### 1. Fetch Video Info
```bash
python3 scripts/download.py info "URL"
```

### 2. Download Specific Format
```bash
python3 scripts/download.py download "URL" "FORMAT_ID"
```

## Safety & Storage
-   This skill is intended for temporary processing.
-   **CRITICAL:** Always delete the downloaded file after the user receives it to maintain disk space.
