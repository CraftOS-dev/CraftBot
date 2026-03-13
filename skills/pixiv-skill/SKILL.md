---
name: pixiv
description: Access Pixiv for searching illustrations, manga, and viewing rankings. Supports searching by keyword and viewing daily/weekly/monthly rankings.
---

# Pixiv Skill

This skill allows searching and browsing Pixiv illustrations.

## Setup

Before using, you must have a valid Pixiv Refresh Token.
The token is stored in `config.json` inside the skill directory.

To configure:
1.  Ask the user for their Pixiv Refresh Token.
2.  Run: `node skills/pixiv/scripts/pixiv-cli.js login <REFRESH_TOKEN>`

## Usage

### Searching Illustrations

To search for illustrations by keyword:

```bash
node skills/pixiv/scripts/pixiv-cli.js search "KEYWORD" [PAGE]
```

Example:
```bash
node skills/pixiv/scripts/pixiv-cli.js search "miku" 1
```

Returns a JSON array of illustration details (title, url, tags, user, etc.).

### Viewing Rankings

To view rankings:

```bash
node skills/pixiv/scripts/pixiv-cli.js ranking [MODE] [PAGE]
```

Modes: `day`, `week`, `month`, `day_male`, `day_female`, `week_original`, `week_rookie`, `day_ai`.
Default is `day`.

Example:
```bash
node skills/pixiv/scripts/pixiv-cli.js ranking day
```

### Viewing User Profile

To view a user's profile details:

```bash
node skills/pixiv/scripts/pixiv-cli.js user <USER_ID>
```

Example:
```bash
node skills/pixiv/scripts/pixiv-cli.js user 11
```

### Viewing Logged-in User Profile (Me)

To view the profile of the currently logged-in account (based on Refresh Token):

```bash
node skills/pixiv/scripts/pixiv-cli.js me
```

### Viewing Followed Users (Following)

To list users that the logged-in account follows:

```bash
node skills/pixiv/scripts/pixiv-cli.js following [PAGE]
```

### Viewing Feed (New Works from Followed Users)

To view latest illustrations from followed users:

```bash
node skills/pixiv/scripts/pixiv-cli.js feed [RESTRICT] [PAGE]
```

`RESTRICT` can be `all`, `public`, or `private`. Default is `all`.

### Downloading Illustrations

To download an illustration (single image, manga/multiple, or ugoira zip):

```bash
node scripts/pixiv-cli.js download <ILLUST_ID>
```

Files are saved to `downloads/<ILLUST_ID>/`.
Returns JSON containing the list of downloaded files.

### Publishing Illustrations (New)

To publish a new illustration directly to Pixiv using the AppAPI v2 (pure code, no browser needed):

```bash
node scripts/pixiv-cli.js post <FILEPATH> "<TITLE>" "[TAGS_COMMA_SEPARATED]" [VISIBILITY]
```

- `VISIBILITY`: `public` (default), `login_only`, `mypixiv`, or `private`.
- Automatic AI-generated tagging (`illust_ai_type: 2`) is applied by default.

Example:
```bash
node scripts/pixiv-cli.js post "./output.png" "My New Art" "Original, Girl, AI" private
```

## How to get a Token (for User)

If the user asks how to get a token:
1.  Direct them to look up "Pixiv Refresh Token" or use a tool like `gppt` (Get Pixiv Token).
2.  Or tell them to log in to Pixiv in their browser, and look for the `refresh_token` in Local Storage or Cookies (though OAuth refresh token is cleaner).
3.  The easiest way for non-technical users is to use a helper script, but we don't have one here. Just ask them to provide it.
