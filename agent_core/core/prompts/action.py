# -*- coding: utf-8 -*-
"""
Action selection prompts for agent_core.

This module contains prompt templates for action routing and selection.
"""

# Used in User Prompt when asking the model to select an action from the list of candidates
# core.action.action_router.ActionRouter.select_action
SELECT_ACTION_PROMPT = """
<rules>
Action Selection Rules:
- use 'send_message' ONLY for simple responses or acknowledgments.
- use 'ignore' when user's chat does not require any reply or action.
- For ANY task requiring work beyond simple chat, use 'task_start' FIRST.
- To use 3rd party tools or MCP to communicate with the user or execute task, use 'task_start' FIRST to gain access to 3rd party tools and MCP.

Task Mode Selection (when using 'task_start'):
- Use task_mode='simple' for:
  * Quick lookups (weather, time, search queries)
  * Single-answer questions (calculations, conversions)
  * Tasks completable in 2-3 actions
  * No planning or verification needed
- Use task_mode='complex' for:
  * Multi-step work (research, analysis, coding)
  * File operations or system changes
  * Tasks requiring planning and verification
  * Anything needing user approval before completion

Simple Task Workflow:
1. Use 'task_start' with task_mode='simple'
2. Execute actions directly to get the result
3. Use 'send_message' to deliver the result
4. Use 'task_end' immediately after delivering result (no user confirmation needed)

Complex Task Workflow:
1. Use 'task_start' with task_mode='complex'
2. Use 'send_message' to acknowledge receipt (REQUIRED)
3. Use 'task_update_todos' to plan the work following: Acknowledge -> Collect Info -> Execute -> Verify -> Confirm -> Cleanup
4. Execute actions to complete each todo
5. Use 'task_end' ONLY after user confirms the result is acceptable

Critical Rules:
- DO NOT use 'send_message' to claim task completion without actually doing the work.
- This is action selection is for conversation mode, it only has limited actions. Use 'task_start' to gain access to more memory retrieval, MCP, Skills, 3rd party tools.
- Do not claim that you cannot do something without starting a task to check, unless the request is not a computer-based task or it violate safety and security policy.
</rules>

<parallel_actions>
You MAY start multiple independent tasks in parallel by including multiple task_start actions.
Example: User asks "research topic A and topic B" → start both tasks simultaneously.
Only task_start can be parallelized. send_message and ignore must run alone.
</parallel_actions>

<notes>
- The action_name MUST be one of the listed actions.
- Provide every required parameter for the chosen action, respecting the expected type, description, and example.
- Keep parameter values concise and directly useful for execution.
- Always use double quotes around strings so the JSON is valid.
</notes>

<output_format>
Return ONLY a valid JSON object with this structure and no extra commentary:
{{
  "reasoning": "<brief reasoning about what actions to take>",
  "actions": [
    {{
      "action_name": "<name of the chosen action>",
      "parameters": {{
        "<parameter name>": <value>
      }}
    }}
  ]
}}

For parallel actions, include multiple entries in the "actions" array.
For a single action, use an array with one entry.

Example (single action):
{{
  "reasoning": "User asked about weather, starting a simple task",
  "actions": [
    {{"action_name": "task_start", "parameters": {{"task": "Check weather", "task_mode": "simple"}}}}
  ]
}}

Example (parallel actions - starting multiple tasks):
{{
  "reasoning": "User asked to research two topics, starting both tasks in parallel",
  "actions": [
    {{"action_name": "task_start", "parameters": {{"task": "Research topic A", "task_mode": "complex"}}}},
    {{"action_name": "task_start", "parameters": {{"task": "Research topic B", "task_mode": "complex"}}}}
  ]
}}
</output_format>

<actions>
Here are the available actions, including their descriptions and input schema:
{action_candidates}
</actions>

<objective>
Here is your goal:
{query}

Your job is to choose the best action from the action library and prepare the input parameters needed to run it immediately.
</objective>

{memory_context}

---

{event_stream}
"""

# Used in User Prompt when asking the model to select an action from the list of candidates
# core.action.action_router.ActionRouter.select_action_in_task
# KV CACHING OPTIMIZED: Static content FIRST, session-static in MIDDLE, dynamic (event_stream) LAST
SELECT_ACTION_IN_TASK_PROMPT = """
<rules>
Todo Workflow Phases (follow this order):
1. ACKNOWLEDGE - Send message to user confirming task receipt
2. COLLECT INFO - Gather all required information before execution
3. EXECUTE - Perform the actual work (can have multiple todos)
4. VERIFY - Check outcome meets the task requirements
5. CONFIRM - Present result to user and await approval
6. CLEANUP - Remove temporary files if any

Action Selection Rules:
- Select action based on the current todo phase (Acknowledge/Collect/Execute/Verify/Confirm/Cleanup)
- Use 'task_update_todos' to create a plan and track progress: mark current as 'in_progress' when starting, 'completed' when done
- Use 'send_message' for acknowledgments, progress updates, and presenting results
- Use 'send_message' when you need information from user during COLLECT phase
- Use 'task_end' ONLY after user confirms the result is acceptable

Adaptive Execution:
- If you lack information during EXECUTE, go back to COLLECT phase (add new collect todos)
- If VERIFY fails, either re-EXECUTE or go back to COLLECT more info
- DO NOT proceed to next phase until current phase requirements are met
- If you need an action not in the available list, use 'add_action_sets' to add the required capability
- Use 'list_action_sets' to see what action sets are available if unsure

Critical Rules:
- The selected action MUST be from the actions list. If none suitable, set action_name to "" (empty string).
- DO NOT SPAM the user. Max 2 retries for questions before skipping.
- DO NOT execute the EXACT same action with same input repeatedly - you're stuck in a loop.
- DO NOT use 'send_message' to claim completion without doing the work.
- DO NOT use 'task_end' without user approval of the final result.
- Use 'task_update_todos' as FIRST step to create a plan for the task.
- When all todos completed AND user approved, use 'task_end' with status 'complete'.
- If unrecoverable error, use 'task_end' with status 'abort'.
- In GUI mode: only ONE UI interaction per action. Switch to CLI mode using 'switch_mode' action when task is complete.
- You must provide concrete parameter values for the action's input_schema.

File Reading Best Practices:
- read_file returns content with line numbers in cat -n format
- For large files, use offset/limit parameters for pagination:
  * Default reads first 2000 lines - check has_more to know if more exists
  * Use offset to skip to specific line numbers
  * Use limit to control how many lines to read
- To find specific content in large files:
  1. Use grep_files with keywords to locate relevant sections
  2. Note the line numbers from grep results
  3. Use read_file with appropriate offset to read that section
- DO NOT repeatedly read entire large files - use targeted reading with offset/limit
</rules>

<parallel_actions>
Parallel Action Execution:
When multiple actions are completely independent (no action depends on another's output),
you SHOULD batch up to 10 of them in a single step to maximize efficiency.

Good candidates for parallelization:
- Multiple read_file() calls for different files
- Multiple web_search() or memory_search() calls
- Any combination of read-only operations
Example: read_file("a.txt") + read_file("b.txt") + grep_files("pattern")
Example: web_search("query1") + web_search("query2") + memory_search("topic")

Never parallelize these:
- Write/mutate operations: write_file, stream_edit, clipboard_write
- GUI interactions: mouse_click, mouse_move, keyboard_type, scroll, etc.
- Task/state management: task_end, task_update_todos, set_mode, wait
- Action set changes: add_action_sets, remove_action_sets
- send_message

RULES:
1. Never parallelize an action that depends on another action's output.
2. If any selected action is non-parallelizable, it must be the ONLY action in that step.
</parallel_actions>

<reasoning_protocol>
Before selecting an action, you MUST reason through these steps:
1. Identify the current todo from the [todos] event (marked [>] in_progress or first [ ] pending).
2. Determine which phase this todo belongs to (Acknowledge/Collect/Execute/Verify/Confirm/Cleanup).
3. Analyze what "done" means for this specific todo.
4. Check the event stream to see if the required action was already performed.
5. If the todo is complete, select action to update todos.
6. If not complete, select the action needed to complete it.
7. Consider warnings in event stream and avoid repeated patterns.
</reasoning_protocol>

<notes>
- Provide every required parameter for the chosen action, respecting each field's type, description, and example.
- Keep parameter values concise and directly useful for execution.
- Always use double quotes around strings so the JSON is valid.
- DO NOT return empty response. When encounter issue, return 'send_message' to inform user.
</notes>

<output_format>
Return ONLY a valid JSON object with this structure and no extra commentary:
{{
  "reasoning": "<chain-of-thought about current todo, its phase, completion status, and decision>",
  "actions": [
    {{
      "action_name": "<name of the chosen action>",
      "parameters": {{
        "<parameter name>": <value>
      }}
    }}
  ]
}}

For parallel actions, include multiple entries in the "actions" array.
For a single action, use an array with one entry.

Example (single action):
{{
  "reasoning": "Need to update todos to track progress",
  "actions": [
    {{"action_name": "task_update_todos", "parameters": {{"todos": [...]}}}}
  ]
}}

Example (parallel actions):
{{
  "reasoning": "Need to read two config files to understand the setup",
  "actions": [
    {{"action_name": "read_file", "parameters": {{"path": "config.json"}}}},
    {{"action_name": "read_file", "parameters": {{"path": "settings.yaml"}}}}
  ]
}}
</output_format>

<actions>
This is the list of action candidates, each including descriptions and input schema:
{action_candidates}
</actions>

{agent_state}

{task_state}

<objective>
Here is your goal:
{query}

Your job is to reason about the current state, then select the next action and provide the input parameters so it can be executed immediately.
</objective>

{memory_context}

---

{event_stream}
"""

# Compact action space prompt for GUI mode (UI-TARS style)
# This is a hardcoded prompt that describes all available GUI actions in a compact format
GUI_ACTION_SPACE_PROMPT = """## Action Space

mouse_click(x=<int>, y=<int>, button='left', click_type='single') # Click at (x,y). button: 'left'|'right'|'middle'. click_type: 'single'|'double'.
mouse_move(x=<int>, y=<int>, duration=0) # Move cursor to (x,y). Optional duration in seconds for smooth move.
mouse_drag(start_x=<int>, start_y=<int>, end_x=<int>, end_y=<int>, duration=0.5) # Drag from start to end position.
mouse_trace(points=[{x, y, duration}, ...], relative=false, easing='linear') # Move through waypoints. easing: 'linear'|'easeInOutQuad'.
keyboard_type(text='<string>', interval=0) # Type text at current focus. Use \\n for Enter. interval=delay between keystrokes.
keyboard_hotkey(keys='<combo>') # Send key combo. Examples: 'ctrl+c', 'alt+tab', 'enter'. Use + to combine keys.
scroll(direction='<up|down>') # Scroll one viewport in direction.
window_control(operation='<op>', title='<substring>') # operation: 'focus'|'close'|'maximize'|'minimize'. Matches window by title substring.
send_message(message='<string>', wait_for_user_reply=false) # Send message to user. Set wait_for_user_reply=true to pause for response.
wait(seconds=<number>) # Pause for seconds (max 60).
set_mode(target_mode='<cli|gui>') # Switch agent mode. Use 'cli' when GUI task is complete.
task_update_todos(todos=[{content, status}, ...]) # Update todo list. status: 'pending'|'in_progress'|'completed'.
"""

# KV CACHING OPTIMIZED: Static content FIRST, session-static in MIDDLE, dynamic (event_stream) LAST
SELECT_ACTION_IN_GUI_PROMPT = """
<objective>
You are a GUI agent. You are given a goal, reasoning and event stream of your past actions. You need perform the next action to complete the task.
Your job is to select the best next GUI action based on the latest reasoning, and provide the input parameters so it can be executed immediately.
</objective>

<rules>
GUI Action Selection Rules:
- Select the appropriate action according to the given task.
- This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.
- Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions. E.g. if you click on Firefox and a window doesn't open, try wait and taking another screenshot.
- Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.
- If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.
- Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges.
- use 'send_message' when you want to communicate or report to the user.
- If the current todo is complete, use 'task_update_todos' to mark it as completed and move on.
- If the result of the task has been achieved, you MUST use 'set_mode' action to switch to CLI mode.
- DO NOT perform more than one action at a time. For example, if you have to type in a search bar, you should only perform the typing action, not typing and selecting from the drop down and clicking on the button at the same time.
</rules>

<output_format>
Return ONLY a valid JSON object with this structure and no extra commentary:
{{
  "action_name": "<name of the chosen action, or empty string if none apply>",
  "parameters": {{
    "<parameter name>": <value>,
    "...": <value>
  }}
}}
</output_format>

<notes>
- Provide every required parameter for the chosen action, respecting each field's type, description, and example.
- Keep parameter values concise and directly useful for execution.
- Always use double quotes around strings so the JSON is valid.
- DO NOT return empty response. When encounter issue (), return 'send message' to inform user.
</notes>

{agent_state}

{task_state}

{gui_action_space}

{memory_context}

---

{event_stream}
"""

# Used for simple task mode - streamlined action selection without todo workflow
# KV CACHING OPTIMIZED: Static content FIRST, session-static in MIDDLE, dynamic (event_stream) LAST
SELECT_ACTION_IN_SIMPLE_TASK_PROMPT = """
<rules>
Simple Task Execution Rules:
- This is a SIMPLE task - complete it quickly and efficiently
- NO todo list management required - just execute actions directly
- NO acknowledgment phase required - proceed directly to execution
- Select actions that directly accomplish the goal
- Use 'send_message' to report the final result to the user
- Use 'task_end' with status 'complete' IMMEDIATELY after delivering the result
- NO user confirmation required - end task right after sending the result

Action Selection:
- Choose the most direct action to accomplish the goal
- Prefer single-shot actions that return results immediately
- If multiple actions needed, execute sequentially without planning

Critical Rules:
- DO NOT use 'task_update_todos' - simple tasks don't use todo lists
- You do not have to wait for user approval - end task after result is delivered
- After delivering the result, use 'task_end' to end the task
- If stuck or error, use 'task_end' with status 'abort'
</rules>

<parallel_actions>
Parallel Action Execution:
When multiple actions are completely independent (no action depends on another's output),
you SHOULD batch up to 10 of them in a single step to maximize efficiency.

Good candidates for parallelization:
- Multiple read_file() calls for different files
- Multiple web_search() or memory_search() calls
- Any combination of read-only operations
Example: read_file("a.txt") + read_file("b.txt") + grep_files("pattern")
Example: web_search("query1") + web_search("query2") + memory_search("topic")

Never parallelize these:
- Write/mutate operations: write_file, stream_edit, clipboard_write
- GUI interactions: mouse_click, mouse_move, keyboard_type, scroll, etc.
- Task/state management: task_end, wait
- Action set changes: add_action_sets, remove_action_sets
- send_message

RULES:
1. Never parallelize an action that depends on another action's output.
2. If any selected action is non-parallelizable, it must be the ONLY action in that step.
</parallel_actions>

<reasoning_protocol>
Before selecting an action, quickly reason through:
1. What is the goal of this simple task?
2. What has been done so far (check event stream)?
3. What is the most direct action to accomplish/complete the goal?
4. If result was delivered, end the task.
</reasoning_protocol>

<notes>
- Keep it simple and fast
- No ceremony, just results
- Always use double quotes around strings so the JSON is valid
- DO NOT return empty response. When encounter issue, return 'send_message' to inform user.
</notes>

<output_format>
Return ONLY a valid JSON object:
{{
  "reasoning": "<brief reasoning about current state and what action to take>",
  "actions": [
    {{
      "action_name": "<action name>",
      "parameters": {{ ... }}
    }}
  ]
}}

For parallel actions, include multiple entries in the "actions" array.
For a single action, use an array with one entry.
</output_format>

<actions>
{action_candidates}
</actions>

{agent_state}

{task_state}

<objective>
SIMPLE TASK - Execute quickly:
{query}

Reason briefly, then select the next action to complete this task efficiently.
</objective>

---

{memory_context}

{event_stream}
"""

__all__ = [
    "SELECT_ACTION_PROMPT",
    "SELECT_ACTION_IN_TASK_PROMPT",
    "SELECT_ACTION_IN_GUI_PROMPT",
    "SELECT_ACTION_IN_SIMPLE_TASK_PROMPT",
    "GUI_ACTION_SPACE_PROMPT",
]
