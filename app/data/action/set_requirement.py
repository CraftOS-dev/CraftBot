from agent_core import action


@action(
    name="set_requirement",
    description=(
        "Record the definition of done: the measurable checks the finished result must pass. Verify tests the "
        "result against it, and it is kept verbatim when older events are summarized. It is the scope of the "
        "result, not a work plan (update_todos). Call it before substantial work, when the scope changes, and in "
        "Verify to set each status. Always send the full list.\n"
        "Rules:\n"
        "1. Each instruction or constraint the user gave is an item, in their words, with their numbers and the "
        "tolerance an expert would accept (1,500 words: 1,400 to 1,600).\n"
        "2. Add every check an expert in the field would apply, including ones the user did not ask for.\n"
        "3. One measurement per item; many items may share a dimension.\n"
        "4. Each done_when has a number that separates expert from mediocre work: a minimum, range, age limit, "
        "duration, size or count of parts. Never a count of 1, never a quality word (comprehensive, concise, "
        "readable); if the user gave no number, set the expert's.\n"
        "5. An item that would fit any other task is too generic.\n"
        "Substantial work usually needs 10 or more items."
    ),
    mode="ALL",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "requirements": {
            "type": "array",
            "description": (
                'Items {"dimension", "requirement", "done_when", "status": "pending" (default) | "satisfied" | '
                '"violated" (fix before delivering)}. For a relaxed Kyoto trip under ¥200,000:\n'
                'Good: {"dimension":"budget","requirement":"Total under ¥200,000","done_when":"Itemized costs sum '
                'to at most ¥200,000"}\n'
                'Good: {"dimension":"budget","requirement":"Current prices","done_when":"Every price from a source '
                'checked within 14 days"}\n'
                'Good: {"dimension":"pace","requirement":"Relaxed","done_when":"At most 3 timed activities per day"}\n'
                'Bad: {"dimension":"content","requirement":"Comprehensive itinerary","done_when":"All key '
                'attractions covered"}'
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

        result = iai.InternalActionInterface.update_requirements(
            requirements, session_id=input_data.get("_session_id")
        )
        status = "success" if result.get("status") in ("ok", "success") else "error"
        return {"status": status}

    return {"status": "success"}
