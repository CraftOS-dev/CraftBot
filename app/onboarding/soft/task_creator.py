# -*- coding: utf-8 -*-
"""
Soft onboarding task creator.

Creates a task that conducts a conversational interview to build
the user profile and populate USER.md and AGENT.md.
"""

from typing import TYPE_CHECKING

from app.logger import logger

if TYPE_CHECKING:
    from app.task.task_manager import TaskManager


SOFT_ONBOARDING_TASK_INSTRUCTION = """
Conduct a friendly conversational interview to learn about the user.

Your goal is to gather information to personalize the agent experience efficiently.
Ask MULTIPLE related questions together to reduce back-and-forth turns.

INTERVIEW FLOW (4 batches):

1. IDENTITY BATCH - Start with warm greeting and ask together:
   - What should I call you?
   - What do you do for work?
   - Where are you based?
   (Infer timezone from their location, keep this silent)

2. PREFERENCES BATCH - Ask together:
   - Do you prefer casual or formal communication?
   - Should I proactively suggest things or wait for instructions?
   - What types of actions should I ask your approval for?

3. MESSAGING PLATFORM:
   - Which messaging platform should I use for notifications? (Telegram/WhatsApp/Discord/Slack/TUI only)

4. LIFE GOALS (most important question):
   - What are your life goals or aspirations?
   - What would you like me to help you with generally?

IMPORTANT GUIDELINES:
- Ask related questions together using a numbered list format
- Be warm and conversational, not robotic
- Acknowledge their answers before the next batch
- Infer timezone from location (e.g., San Francisco = Pacific Time)
- The life goals question is most important, ask multiple questions if necessary or goal unclear. Guide them to answer this question. Skip if user has no life or goal.
- If user is annoyed by this interview or refuse to answer, just skip, and end task.

After gathering ALL information:
1. Read agent_file_system/USER.md
2. Update USER.md with the collected information using stream_edit (including Life Goals section)
3. Suggest 3-5 specific tasks that can help them achieve their life goals using CraftBot's automation capabilities
4. End the task immediately with task_end (do NOT wait for confirmation)

Start with: "Hi! I'm excited to be your AI assistant. To personalize your experience, let me ask a few quick questions:" then list the first batch.
"""


def create_soft_onboarding_task(task_manager: "TaskManager") -> str:
    """
    Create a soft onboarding interview task.

    This task uses the user-profile-interview skill to conduct
    a conversational Q&A interview and populate USER.md/AGENT.md.

    Args:
        task_manager: TaskManager instance to create the task

    Returns:
        Task ID of the created interview task
    """
    task_id = task_manager.create_task(
        task_name="User Profile Interview",
        task_instruction=SOFT_ONBOARDING_TASK_INSTRUCTION,
        mode="complex",
        action_sets=["file_operations", "core"],
        selected_skills=["user-profile-interview"]
    )

    logger.info(f"[ONBOARDING] Created soft onboarding task: {task_id}")
    return task_id
