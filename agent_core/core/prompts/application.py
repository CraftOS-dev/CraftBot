# -*- coding: utf-8 -*-
"""
Application-specific prompt templates.

Contains prompt templates for Living UI and other application features.
"""

# Per-project facts ONLY. Every stable rule (platform architecture, the
# build loop, gates, debug protocol, quality bar) lives in the
# `living_ui_development` sub-workflow's system prompt
# (app/workflows/living_ui/workflow.py) — the creation task runs with that
# prompt instead of the general agent's, so rules are stated once and
# cached, not re-rendered per turn. If you change the workflow's rules,
# change them THERE.
LIVING_UI_TASK_INSTRUCTION = """Create a Living UI application.

Project ID: {project_id}
Project Name: {project_name}
Theme: {theme}
Project Path: {project_path}

REQUIREMENTS — the complete, binding specification for this app. It was
gathered from the user's configuration and interview BEFORE this task
started (also saved at {project_path}/reference/requirements.md); the user
will NOT answer further questions, so never ask — where the spec is
silent, decide and build:

{requirements}

Reference files the user provided (design sketches, screenshots,
documents) — study each BEFORE the wireframe; view images with
describe_image:
{reference_files}

The platform computes and executes the build every turn. When a turn
carries a <step_directive> block, follow it exactly; otherwise your only
build duty is the initial scaffold. The build todos are platform-managed —
never edit them."""
