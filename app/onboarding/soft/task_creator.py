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
Conduct a natural conversation with the user to understand their work and life goals.

The user already provided their name, location, language, communication tone, proactivity,
approval settings, and notification platform during setup. These are saved in
agent_file_system/USER.md. Read it first so you know who you're talking to.
Do not re-ask any of that.

Never use scripted or static phrases. Rephrase everything naturally each time.
Match the user's energy and style.

Phase 1: Greeting + Job/Role
Read agent_file_system/USER.md to get the user's name. Greet them by name in your own words.
Ask about their work and what a typical day looks like.
Acknowledge their answer before moving on.

Phase 2: Life Goals Exploration
Ask about their goals and aspirations in your own words.
Follow up on the goal they mention to understand timelines, obstacles, what success looks like.
If the user is engaged, continue exploring what else they're working toward, habits they want
to build, skills they want to develop, what would make their day-to-day easier.
If the user is brief or disengaged, wrap up gracefully. Do not push for more question. Move on to phase 3.
If the user has no goals or refuses, respect that and move on to phase 3.

Phase 3: How CraftBot Helps + Task Suggestions
In one message, explain how CraftBot can help them based on what you learned, and suggest
1-3 specific tasks. Each suggestion must say exactly what you will do and what the
deliverable is. Do not describe generic tasks — describe actions with concrete outputs.
At least one suggestion must be something you can execute immediately after this conversation
and deliver a tangible result.
Bad example: "Research synthesis - I can summarize AGI papers"
Good example: "I'll research the top 5 AGI breakthroughs this month and send you a summary now."

After the conversation:
1. Tell the user to wait a moment while you update your knowledge about them.
2. Read agent_file_system/USER.md using read_file.
3. Update USER.md using stream_edit:
   - Update the Job field
   - Write their goals as free-form text under Life Goals
   - Write personality observations under Personality
   - Do not overwrite name, location, language, tone, proactivity, approval, or messaging platform
4. Update agent_file_system/AGENT.md if user provided a name for the agent.
5. Send your explanation of how CraftBot can help and your task suggestions.
6. End the task with task_end. Do not wait for confirmation.
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
        mode="simple",
        action_sets=["file_operations", "core"],
        selected_skills=["user-profile-interview"],
    )

    logger.info(f"[ONBOARDING] Created soft onboarding task: {task_id}")
    return task_id
