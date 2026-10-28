"""Expand only explicitly attached reference sources, without changing them."""

from agent_core import action


@action(
    name="read_reference",
    description="Read more context from a session or agent_app explicitly referenced in this chat. Returns a bounded live page; use nextCursor to read older session messages. Does not run or modify the source.",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "kind": {
            "type": "string",
            "description": "session or agent_app",
            "example": "session",
        },
        "target_id": {
            "type": "string",
            "description": "targetId from the reference context",
            "example": "chat-123",
        },
        "cursor": {
            "type": "string",
            "description": "Optional nextCursor from an earlier page",
            "example": "",
        },
    },
)
async def read_reference(input_data: dict) -> dict:
    from app.references import ReferenceError, create_reference_service

    session_id = input_data.get("_session_id")
    if not session_id:
        return {"error": "A destination session is required."}
    try:
        return await create_reference_service().read(
            {"kind": input_data.get("kind"), "targetId": input_data.get("target_id")},
            session_id,
            input_data.get("cursor") or None,
        )
    except ReferenceError as exc:
        return {"error": str(exc)}
