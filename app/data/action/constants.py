"""Shared constants for agent actions and the agent loop."""

# How long a task parks while waiting on a user reply (3 hours). Used by every
# action that returns wait_for_user_reply and by agent_base's wait re-schedule
# paths — keep them in sync by importing this rather than inlining the number.
WAIT_FOR_REPLY_PARK_DELAY_SECONDS = 10800
