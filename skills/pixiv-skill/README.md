# Pixiv Skill for OpenClaw

A powerful Pixiv integration for OpenClaw, allowing you to search illustrations, view rankings, browse user profiles, download content, and **publish new illustrations** directly from your agent interface.

## Features

- **Search**: Search for illustrations by keyword.
- **Rankings**: View daily, weekly, and monthly rankings.
- **User Profiles**: View public user profiles and stats.
- **My Profile**: View your own logged-in profile.
- **Feed**: View the latest works from users you follow.
- **Following**: List users you are following.
- **Download**: Download illustrations, manga, and ugoira (converted to GIF).
- **Publish (New!)**: Upload and publish illustrations using pure-code AppAPI v2 (no browser required).

## Installation

1. Copy this folder to your OpenClaw skills directory.
2. Install dependencies:
   ```bash
   npm install
   ```

## Configuration

1. Create a `config.json` file in the root of the skill directory.
2. You need a **Pixiv Refresh Token**. 

**config.json**:
```json
{
  "refresh_token": "YOUR_PIXIV_REFRESH_TOKEN"
}
```

Alternatively, set it via CLI:
```bash
node scripts/pixiv-cli.js login <REFRESH_TOKEN>
```

## Usage

### CLI Commands

- **Post Work**: `node scripts/pixiv-cli.js post <filepath> <title> [tags] [visibility]`
  - `visibility`: `public` (default), `login_only`, `mypixiv`, or `private`.
- **Search**: `node scripts/pixiv-cli.js search "keyword" [page]`
- **Ranking**: `node scripts/pixiv-cli.js ranking [mode] [page]`
- **User Profile**: `node scripts/pixiv-cli.js user <user_id>`
- **My Profile**: `node scripts/pixiv-cli.js me`
- **Feed**: `node scripts/pixiv-cli.js feed [restrict] [page]`
- **Following**: `node scripts/pixiv-cli.js following [page]`
- **Download**: `node scripts/pixiv-cli.js download <illust_id>`

## Dependencies

- `@ibaraki-douji/pixivts`: Unofficial Pixiv API client.
- `axios`, `form-data`: For API requests and file uploads.
- `adm-zip`, `gif-encoder-2`, `pngjs`, `jpeg-js`: For Ugoira processing.

## Disclaimer

This project is an unofficial tool and is not affiliated with Pixiv Inc. Use responsibly.
