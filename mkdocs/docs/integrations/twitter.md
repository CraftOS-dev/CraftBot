# Twitter

The Twitter integration connects the agent to your X (Twitter) account with your own developer app keys over OAuth 1.0a. The agent can post, reply to, quote, delete, look up, and search tweets, read timelines and mentions, like, retweet, and bookmark, manage lists and direct messages, upload media, and follow, block, or mute users. A polling listener turns mentions into events the agent reacts to.

## Requirements

| Requirement | Details |
|---|---|
| X (Twitter) account | The agent acts as this account for every API call |
| Developer account | Free tier works for posting. Sign up at [developer.twitter.com](https://developer.twitter.com/en/portal/dashboard) |
| Project and standalone app | OAuth 1.0a enabled with Read and Write permissions |
| Four keys | Consumer Key, Consumer Secret, Access Token, and Access Token Secret |
| Free tier limit | About 1500 posts per month per app, which is why each user supplies their own keys |
| Network access | CraftBot calls `api.twitter.com` over HTTPS |

## Setup

1. Open [developer.twitter.com/en/portal/dashboard](https://developer.twitter.com/en/portal/dashboard). Sign up for a developer account if you do not have one. The free tier is enough for posting.
2. Create a **Project**, then a standalone **App** inside it.
3. In the app's **User authentication settings**, enable **OAuth 1.0a** with **Read and Write** permissions. Add DM permission if you want the agent to send direct messages.
4. On the **Keys and tokens** tab, copy the **Consumer Key** and **Consumer Secret**.
5. Scroll down, generate the **Access Token** and **Access Token Secret**, and copy both.
6. In CraftBot, open **Settings → Integrations → Twitter/X** and paste all four values, or run `/twitter login <api_key> <api_secret> <access_token> <access_token_secret>`.
7. Verify with `/twitter status`. It shows the connected username and the watch tag if one is set.

`/twitter logout` removes the credential and stops the listener.

## How it connects

**Authentication.** The integration uses OAuth 1.0a, so every request is signed with your four keys using HMAC-SHA1. There is no shared app and no browser flow. On first connect it resolves and stores your user ID and username, so it never asks for your handle again. The keys and resolved identity are stored in the credential store as `twitter.json`. See [Credentials](credentials.md).

**Polling listener.** While connected, CraftBot polls your mentions every 30 seconds. It tracks the newest mention with `since_id` so each mention dispatches exactly once, and it deduplicates by tweet ID. After a 429 rate-limit response the poller sleeps 60 seconds before trying again rather than retrying immediately.

**Watch tag.** If a watch tag is set, only mentions containing that tag dispatch, and the instruction the agent runs is the text after the tag with any leading @-mentions stripped. With no tag set, every mention dispatches. Set the tag from chat with `set_twitter_watch_tag` or under [Configuration](#configuration).

**Replies.** When the agent responds to a mention, it posts a reply to that tweet. Posts are capped at 280 characters, and the agent trims or splits longer text into a thread before posting.

## What the agent can do

The 46 Twitter actions are grouped into action sets (`twitter_tweets`, `twitter_engagement`, `twitter_users`, `twitter_lists`, `twitter_dms`, `twitter_media`, `twitter_listener`) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Tweets

| Action | Purpose |
|---|---|
| `post_tweet` | Post a tweet |
| `reply_to_tweet` | Reply to a tweet |
| `delete_tweet` | Delete a tweet |
| `get_tweet` | Fetch a single tweet by ID |
| `lookup_tweets` | Batch-look up to 100 tweets by their IDs |

### Search

| Action | Purpose |
|---|---|
| `search_tweets` | Search recent tweets |

### Timeline and mentions

| Action | Purpose |
|---|---|
| `get_twitter_timeline` | Get recent tweets from a user's timeline (yours if omitted) |
| `get_twitter_mentions` | Get recent mentions of a user (yours by default) |

### Quote and hide reply

| Action | Purpose |
|---|---|
| `post_quote_tweet` | Post a quote tweet that wraps another tweet with your commentary |
| `hide_tweet_reply` | Hide or unhide a reply to one of your tweets |

### Media tweets

| Action | Purpose |
|---|---|
| `post_tweet_with_media` | Post a tweet that includes already-uploaded media |

### Likes, retweets, and bookmarks

| Action | Purpose |
|---|---|
| `like_tweet` | Like a tweet |
| `unlike_tweet` | Unlike a previously liked tweet |
| `retweet` | Retweet a tweet |
| `unretweet` | Undo a retweet |
| `add_twitter_bookmark` | Bookmark a tweet |
| `remove_twitter_bookmark` | Remove a tweet from bookmarks |
| `list_twitter_bookmarks` | List your bookmarked tweets |

### Liking users and retweeters

| Action | Purpose |
|---|---|
| `list_tweet_liking_users` | List users who liked a tweet |
| `list_tweet_retweeted_by` | List users who retweeted a tweet |

### Users

| Action | Purpose |
|---|---|
| `get_twitter_user` | Look up a user by username |
| `get_twitter_me` | Get the authenticated user's profile |
| `follow_twitter_user` | Follow a user by their numeric user ID |
| `unfollow_twitter_user` | Unfollow a user |
| `list_twitter_following` | List who a user is following (yours by default) |
| `list_twitter_followers` | List a user's followers (yours by default) |
| `block_twitter_user` | Block a user |
| `unblock_twitter_user` | Unblock a user |
| `mute_twitter_user` | Mute a user |
| `unmute_twitter_user` | Unmute a previously muted user |

### Lists

| Action | Purpose |
|---|---|
| `create_twitter_list` | Create a new list |
| `get_twitter_list` | Get a list by ID |
| `update_twitter_list` | Update a list's name, description, or privacy |
| `delete_twitter_list` | Delete a list |
| `list_twitter_owned_lists` | List the lists a user owns (yours by default) |
| `add_twitter_list_member` | Add a user to a list |
| `remove_twitter_list_member` | Remove a user from a list |
| `list_twitter_list_members` | List members of a list |
| `list_twitter_list_tweets` | List recent tweets in a list |

### Direct messages

| Action | Purpose |
|---|---|
| `send_twitter_dm` | Send a one-on-one direct message, creating the conversation if needed |
| `send_twitter_dm_to_conversation` | Send a DM into an existing conversation by ID |
| `create_twitter_group_dm` | Create a group DM and send the first message |
| `list_twitter_dm_events` | List recent DM events across all your conversations |
| `list_twitter_dm_events_with_user` | List DM events in the conversation with a specific user |

### Media upload

| Action | Purpose |
|---|---|
| `upload_twitter_media` | Upload an image, GIF, or video and return its media ID for a media tweet |

### Listener settings

| Action | Purpose |
|---|---|
| `set_twitter_watch_tag` | Set the keyword the mention listener requires (empty means all mentions trigger) |

## Example requests

```
Post a tweet announcing our launch and include the image at ./launch.png.
```

```
Search for recent tweets mentioning our product and summarize the sentiment.
```

```
Reply to tweet 1789012345 thanking them and inviting them to try the beta.
```

```
Create a private list called "Competitors" and add @acme and @globex to it.
```

```
Only react to mentions that include @craftbot, and run whatever they ask.
```

```
Show my last 20 mentions and tell me which ones are questions I should answer.
```

## Configuration

The watch tag lives in **Settings → Integrations → Twitter/X** and is stored in `twitter_config.json` next to the credential. The listener re-reads it on every poll, so a change applies without reconnecting. You can also set it from chat, which uses the `set_twitter_watch_tag` action.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Watch tag (`watch_tag`) | text, e.g. `@craftbot` | empty | Only mentions containing this tag dispatch, and the text after the tag becomes the instruction. Empty means every mention dispatches |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 403 Forbidden on `post_tweet` | The app permissions are Read-only | Set Read and Write in the portal's User authentication settings, then regenerate the access token and secret. The old tokens keep Read-only access |
| "Rate limit exceeded" or 429 | The free tier has tight per-endpoint limits | Wait for the window to reset. The listener already backs off 60 seconds, so do not add retry loops |
| Post rejected as too long | Tweets are capped at 280 characters | Ask the agent to trim the text or split it into a thread |
| Agent stops reacting to mentions | A watch tag is set and the mentions do not contain it | Check the watch tag in **Settings → Integrations → Twitter/X**, or clear it to react to all mentions |
| DM actions fail | The app does not have DM permission | Enable DM permission in User authentication settings and regenerate the access token |
| Login fails or `/twitter status` shows not connected | One of the four keys is wrong, or they are from different apps | Recopy all four values from the same app's Keys and tokens tab and run `/twitter login` again |

## Next

- [LinkedIn](linkedin.md): profile and posting actions over one-click OAuth
- [Credentials](credentials.md): where the keys are stored and how `/cred status` reports them
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
