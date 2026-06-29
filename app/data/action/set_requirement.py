from agent_core import action


@action(
    name="set_requirement",
    description=(
        "Record (or update) the concrete, checkable requirements that define DONE for this task's deliverable. "
        "This is the SCOPE of the output, NOT a plan of work — for work-tracking, use 'task_update_todos'. "
        "Call this in the very first step of a complex task (BEFORE acknowledging the user) to lock in WHAT the "
        "finished deliverable must contain and look like; call it again during Collect if new information forces a scope update; "
        "call it again during Verify to mark each item satisfied or violated.\n\n"
        "Every requirement MUST be concrete and falsifiable. A reader who has never seen this task should be able to look at the "
        "deliverable, read your `done_when`, and decide pass/fail without further interpretation.\n\n"
        "BANNED phrasing (these are aspirations, not requirements): 'high quality', 'good design', 'comprehensive', 'professional', "
        "'polished', 'thorough', 'appropriate', 'well-structured', 'beautiful', 'engaging', 'detailed enough', 'as needed'. "
        "If a requirement reads like a compliment instead of a check, REWRITE it.\n\n"
        "Cover every dimension that materially shapes the output. Typical dimensions include but are not limited to: "
        "content (what specific topics/sections/data must be included), "
        "structure (ordering, section hierarchy, navigation), "
        "length (per section, per page, total), "
        "style/tone (voice, register, reading level, vocabulary), "
        "design (typography choices, color, spacing, hierarchy, layout rules), "
        "media (which images, charts, diagrams, tables — and where), "
        "format (file type, output target, encoding), "
        "data_sources (which sources must be cited, freshness requirements), "
        "audience (who reads this and what they need), "
        "constraints (what is forbidden, banned, or limited).\n\n"
        "Always provide the COMPLETE current requirement list. This action can be executed in parallel with send_message, but do not "
        "call multiple set_requirement actions at the same time."
    ),
    mode="ALL",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "requirements": {
            "type": "array",
            "description": (
                'Array of requirement objects. Each object MUST have these keys: '
                '"dimension" (string: which aspect of the deliverable — e.g. "content", "structure", "length", "style", '
                '"design", "media", "tone", "format", "data_sources", "audience", "constraints"), '
                '"requirement" (string: the SPECIFIC requirement, written so a critic can check it. '
                'Concrete and falsifiable. NEVER vague praise.), '
                '"done_when" (string: the concrete test the deliverable must pass to satisfy this requirement). '
                'Optional: "status" — one of "pending" (default, not yet checked), "satisfied" (Verify confirmed), '
                '"violated" (Verify found it failing — triggers rework).\n\n'
                'Good example: {"dimension":"content","requirement":"Include a chronological version history covering every major release from launch through the latest patch","done_when":"A markdown table exists with one row per major version, each row listing version number, release date, and the headline feature/change"}.\n\n'
                'Bad example (DO NOT WRITE): {"dimension":"content","requirement":"Comprehensive history of the game","done_when":"All major events are covered"}.'
            ),
            "required": True,
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates whether the requirement list was updated successfully.",
        }
    },
    test_payload={
        "requirements": [
            {
                "dimension": "content",
                "requirement": "Include sections: Overview, History (chronological table), Gameplay Mechanics, Editions Comparison Table, Reception with cited Metacritic/OpenCritic scores, Cultural Impact, Developer Information",
                "done_when": "Each named section header appears as an H2 in the markdown output and contains body text",
                "status": "pending",
            },
            {
                "dimension": "length",
                "requirement": "Each top-level section is at least 4 substantive paragraphs OR an equivalent dense table; total deliverable is at least the length of a long-read feature article",
                "done_when": "Every H2 section in the file passes 4-paragraph minimum on read-back, or contains a table with 6+ rows",
                "status": "pending",
            },
            {
                "dimension": "media",
                "requirement": "At least one tabular element per major data-dense section (history, editions, reception); never use emoji as bullet markers",
                "done_when": "grep of the deliverable shows ≥3 markdown tables; grep shows zero leading emoji bullets in body text",
                "status": "pending",
            },
        ],
        "simulated_mode": True,
    },
)
def set_requirement(input_data: dict) -> dict:
    """Emit the requirement contract into the event stream so the agent reads it back on every subsequent step."""
    requirements = input_data.get("requirements", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not simulated_mode:
        import app.internal_action_interface as iai

        result = iai.InternalActionInterface.update_requirements(requirements)
        status = "success" if result.get("status") in ("ok", "success") else "error"
        return {"status": status}

    return {"status": "success"}
