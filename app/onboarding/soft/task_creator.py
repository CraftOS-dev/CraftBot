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

Your goal is to gather information to personalize the agent experience:
1. Learn their name and what they do
2. Understand their communication preferences (casual/formal, brief/detailed)
3. Determine how proactive they want you to be
4. Identify what types of actions need their approval

IMPORTANT GUIDELINES:
- Be warm and conversational, not robotic
- Ask ONE question at a time and wait for their response
- Acknowledge their answers before asking the next question
- Keep it natural - this is a conversation, not an interrogation
- If they seem uncomfortable, offer to skip questions

After gathering information:
1. Read agent_file_system/USER.md
2. Update USER.md with the collected information using stream_edit
3. You are free to add extra information provided by user while respecting the md file format
4. Send a summary message of what you learned
5. End the task with task_end

Start with a warm greeting and ask what they'd like to be called.
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
