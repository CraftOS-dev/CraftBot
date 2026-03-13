# -*- coding: utf-8 -*-
"""
Skill and action set selection prompts for agent_core.

This module contains prompt templates for skill and action set selection.
"""

# --- Combined Skills and Action Sets Selection ---
# Used by InternalActionInterface.do_create_task() to select both in one LLM call
SKILLS_AND_ACTION_SETS_SELECTION_PROMPT = """
<objective>
You are selecting a skill and action sets for a task. This is a two-part selection:
1. First, select ONE relevant skill (instruction module that guides how to perform work)
2. Then, select action sets (tools the agent needs), considering what the selected skill recommends
</objective>

<task_information>
Task Name: {task_name}
Task Description: {task_description}
Source Platform: {source_platform}
</task_information>

<available_skills>
{available_skills}
</available_skills>

<available_action_sets>
{available_sets}
</available_action_sets>

<instructions>
**Step 1 - Select ONE Skill:**
- Review the task description carefully
- Select AT MOST ONE skill that best matches this specific task
- ONLY select one skill - do NOT select multiple skills
- If no skills are 90% relevant, you MUST leave the skills array empty to save token
- Note: Some skills recommend certain action sets (shown as "recommends: [...]")

**Step 2 - Select Action Sets:**
- The 'core' set is ALWAYS included automatically - do NOT include it
- Include action sets recommended by the selected skill
- Add any additional sets needed based on task requirements:
  - File work → 'file_operations'
  - Web browsing/searching → 'web_research'
  - PDFs/documents → 'document_processing'
  - GUI automation → 'gui_interaction'
  - Running commands → 'shell'
- Select ONLY the sets needed (fewer is better for performance)- 
- If the source platform is an external messaging service, you MUST include that platform's action set, for example:
  - Telegram → include 'telegram' action set
  - Slack → include 'slack' action set
  - CraftBot TUI → no additional action set needed (uses default send_message)
</instructions>

<output_format>
Return ONLY a valid JSON object with:
- "skills": array with at most ONE skill name (or empty if no match)
- "action_sets": array of action set names

Example with skill:
{{"skills": ["code-review"], "action_sets": ["file_operations"]}}

Example without skill:
{{"skills": [], "action_sets": ["web_research"]}}

Example with external platform:
{{"skills": [], "action_sets": ["web_research", "telegram"]}}
</output_format>
"""

# --- Skill Selection (Legacy - kept for backward compatibility) ---
SKILL_SELECTION_PROMPT = """
<objective>
You are selecting skills for a task. Skills provide specialized instructions that help the agent perform specific types of work more effectively.
</objective>

<task_information>
Task Name: {task_name}
Task Description: {task_description}
</task_information>

<available_skills>
{available_skills}
</available_skills>

<instructions>
- Review the task description carefully
- Select skills that directly help with this specific task
- If no skills are relevant, return an empty list []
- Only select skills that provide clear value for this task
- Multiple skills can be selected if they complement each other
</instructions>

<output_format>
Return ONLY a valid JSON array of skill names (strings), with no additional text or explanation:
["skill_name_1", "skill_name_2"]

If no skills are needed, return an empty array:
[]
</output_format>
"""

# --- Action Set Selection (Legacy - kept for backward compatibility) ---
ACTION_SET_SELECTION_PROMPT = """
<objective>
You are selecting action sets for a task. Based on the task description, choose which action sets the agent will need to complete this task.
</objective>

<task_information>
Task Name: {task_name}
Task Description: {task_description}
</task_information>

<available_action_sets>
{available_sets}
</available_action_sets>

<instructions>
- Select ONLY the sets needed for this task (fewer is better for performance)
- The 'core' set is ALWAYS included automatically - do NOT include it in your response
- Consider what capabilities the task requires based on the description, here are some examples:
  - If the task involves files, include 'file_operations'
  - If the task involves web browsing or searching, include 'web_research'
  - If the task involves PDFs or documents, include 'document_processing'
  - If the task involves GUI automation, include 'gui_interaction'
  - If the task involves running commands or scripts, include 'shell'
</instructions>

<output_format>
Return ONLY a valid JSON array of action set names (strings), with no additional text or explanation:
["set_name_1", "set_name_2"]

If no additional sets are needed beyond core, return an empty array:
[]
</output_format>
"""

__all__ = [
    "SKILLS_AND_ACTION_SETS_SELECTION_PROMPT",
    "SKILL_SELECTION_PROMPT",
    "ACTION_SET_SELECTION_PROMPT",
]
