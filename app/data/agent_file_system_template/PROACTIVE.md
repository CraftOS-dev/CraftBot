# Proactive Management

**Last Updated:** `YYYY-MM-DD HH:MM:SS UTC`

## Overview

This document tracks all proactive activities, monitoring targets, and automated interventions.

You can operate proactively based on scheduled activations. Schedules can be hourly (every X hours), daily (at a specific time), weekly (on a specific day), or monthly (on a specific date).

When a schedule fires, you execute a proactive check workflow. First, read PROACTIVE.md to understand configured proactive tasks and their conditions. Then research the agent file system for relevant context - user preferences, project status, organizational priorities.

Evaluate each potential proactive task using a five-dimension rubric. Score each dimension from 1 to 5:
- Impact: How significant is the outcome? (1=negligible, 5=critical)
- Risk: What could go wrong? (1=high risk, 5=no risk)
- Cost: Resources and effort required? (1=very high, 5=negligible)
- Urgency: How time-sensitive? (1=not urgent, 5=immediate)
- Confidence: Will the user accept this? (1=unlikely, 5=certain)

Add the scores. Tasks scoring 18 or above are strong candidates for execution. Tasks scoring 13-17 may be worth doing but might need user input first. Tasks below 13 should be skipped or deferred.

Before acting on any proactive task, follow the tiered permission model:
- Tier 0 (silent read): Searching, analyzing, drafting internally - proceed without asking
- Tier 1 (suggest): Notifying user of findings or recommendations - wait for acknowledgment
- Tier 2 (low-risk): Creating tickets, scheduling reminders, drafting PRs - inform and proceed unless objected
- Tier 3 (high-risk): Emailing external parties, changing configs, touching finances - explicit approval required every time
- Tier 4 (prohibited): Actions disallowed by policy or potentially irreversible harm - never proceed

When requesting permission for proactive tasks, prefix your message with the star emoji to indicate it is a proactive request.

After executing proactive tasks, update PROACTIVE.md with what was done, when, and the outcome.

## Proactive Tasks

### Startup

empty

### Hourly

empty

### Weekly

empty

### Monthly

empty

### Other
