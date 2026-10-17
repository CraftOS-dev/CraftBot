from agent_core import action


@action(
    name="render_ui",
    description=(
        "Create a self-contained HTML document with inline CSS/JavaScript in the output workspace. "
        "Choose this when manipulating inputs, exploring alternatives, inspecting changing data or "
        "tracking progress materially helps the user's goal; no explicit UI request is needed. "
        "Prefer text when reading suffices; never render solely for decoration or topic. "
        "Respect requested formats. "
        "Use semantic, keyboard-usable HTML and addEventListener; every control must work. "
        "No backend, npm/imports, external scripts, external stylesheets or web fonts (no CSS "
        "@import; use --cb-font or system fonts), inline event handlers or secrets. "
        "Never navigate or request permissions; preventDefault on form submits. Other resources "
        "are blocked by CSP. For API fetches declare exact public HTTPS origins in connect_origins "
        "(omit offline); require credential-free browser CORS, loading/recoverable errors, actual "
        "data timestamps and verified units. "
        "Restore window.craftbot.state; call window.craftbot.saveState(object) on changes. "
        "State is JSON: store timer deadlines, not interval counts; serialize timestamps and "
        "reconstruct Dates. To revise, pass artifact_id plus complete replacement HTML; "
        "preserve state keys and normalize obsolete saved enum values. You cannot inspect or "
        "change saved preview state through this action. "
        "Design around the main activity: useful defaults, immediate feedback, a strong focal "
        "value/result and one clear primary action. Keep labeled controls/units near their results; "
        "make selection and progress obvious. Use open sections, whitespace and subtle dividers "
        "instead of nested bordered cards or generic dashboards. Keep advanced settings/tips "
        "behind disclosures and give empty/error states actionable next steps. "
        "Use 15–16px body text, deliberate hierarchy and restrained accents. For live host "
        "light/dark styling use --cb-bg, --cb-surface, --cb-text, --cb-muted, --cb-border, "
        "--cb-accent and --cb-font; bespoke palettes must consistently style page/text/controls "
        "without host-token fallbacks overriding them. "
        "Fit a full-height, resizable 440–900px canvas and usable 360px layout using document-width "
        "responsive CSS (narrower than 440px, the host shows it at phone width). The host supplies "
        "title and revision controls: don't duplicate them, add faux browser chrome or repeat the "
        "title with an intro. "
        "Use purposeful 150–250ms opacity/transform transitions; honor prefers-reduced-motion. "
        "No perpetual decoration, ticking-number animation or delayed controls. "
        "Keep code concise with shared styles/functions so the complete document fits one response. "
        "After rendering, send at most one brief usage sentence; don't re-ask for values adjustable "
        "in the interface."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "title": {
            "type": "string",
            "description": "Short interface title (1–120 characters).",
        },
        "html": {
            "type": "string",
            "description": "Complete HTML/CSS/JS, at most 512 KB.",
        },
        "artifact_id": {
            "type": "string",
            "description": "Optional ID returned by an earlier render_ui in this session; omit for a new interface.",
        },
        "connect_origins": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of at most 8 exact public HTTPS API origins (default HTTPS port). No paths, query strings, credentials, IP addresses, local hosts or wildcards. Omit for offline output.",
        },
    },
    output_schema={
        "status": {"type": "string"},
        "artifact_id": {"type": "string"},
        "revision": {"type": "integer"},
    },
    test_payload={
        "title": "Counter",
        "html": "<button>Count</button>",
        "simulated_mode": True,
    },
)
async def render_ui(input_data: dict) -> dict:
    # CraftBot executes the serialized function body in a fresh namespace.
    import asyncio

    from agent_core.core.session import MAIN_SESSION_ID
    from app.generative_ui import make_artifact

    try:
        artifact = make_artifact(input_data)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not input_data.get("simulated_mode", False):
        from app.internal_action_interface import InternalActionInterface as iai

        session_id = input_data.get("_session_id") or MAIN_SESSION_ID
        if input_data.get("artifact_id"):
            streams = iai.state_manager.event_stream_manager
            if not streams.has_stream(session_id):
                return {
                    "status": "error",
                    "message": "This session has no UI artifact stream.",
                }
            stream = streams.get_stream_by_id(session_id)
            previous = [
                event.ui_artifact
                for event in stream.as_list()
                if event.ui_artifact and event.ui_artifact.get("id") == artifact["id"]
            ]
            if not previous:
                from app.usage.chat_storage import get_chat_storage

                stored = await asyncio.to_thread(
                    get_chat_storage().get_latest_ui_artifact,
                    session_id,
                    artifact["id"],
                )
                if stored:
                    previous = [stored]
            if not previous:
                return {
                    "status": "error",
                    "message": "No artifact with this ID exists in this session.",
                }
            artifact["revision"] = max(a["revision"] for a in previous) + 1
        await iai.do_chat(
            artifact["title"],
            platform="CraftBot Interface",
            session_id=session_id,
            continue_work=True,
            ui_artifact=artifact,
        )
    return {
        "status": "success",
        "artifact_id": artifact["id"],
        "revision": artifact["revision"],
    }
