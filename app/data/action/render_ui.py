from agent_core import action


@action(
    name="render_ui",
    description=(
        "Create an interactive output in CraftBot's separate output workspace using a complete "
        "self-contained HTML document with inline CSS and JavaScript. Choose this action "
        "when interaction materially helps the user accomplish their task: manipulating "
        "inputs, exploring alternatives, inspecting changing information, or tracking progress. "
        "Infer that benefit from the user's goal; they do not need to request a UI. "
        "Prefer a normal text answer when reading alone meets the need. Do not create "
        "an interface merely to decorate an answer or because of its topic. Respect "
        "the user's requested output format. No backend, npm, "
        "imports, external scripts, inline onclick handlers, or API secrets. Use "
        "addEventListener for working controls and semantic, responsive, keyboard-usable "
        "HTML. Read initial JSON state from window.craftbot.state and call "
        "window.craftbot.saveState(object) on changes; persist timer deadlines, not "
        "interval counters. State is JSON: save timestamps as numbers or strings "
        "and reconstruct Date objects on restore; never assume saved objects retain methods. "
        "For browser API requests, declare only the exact public HTTPS origins needed "
        "in connect_origins; omit it for offline outputs. APIs must support browser CORS "
        "without private credentials. Include "
        "loading/error states and real data timestamps. Check API-returned units before conversions. "
        "The result opens in a dedicated full-height canvas beside the conversation, "
        "with host controls for phone preview, fullscreen and revisions. Design the "
        "output as a polished small product, not a chat bubble or a collection of forms. "
        "Use a deliberate visual hierarchy: a concise title, a strong focal point, "
        "readable supporting detail, and one clear primary action. Choose spacing, "
        "type scale and a restrained accent suited to the task. Use the supplied CSS variables "
        "--cb-bg, --cb-surface, --cb-text, --cb-muted, --cb-border, --cb-accent, --cb-font "
        "for neutral surfaces in the host's live light/dark theme. Use readable "
        "15–16px body text, meaningful 28–40px headings, and generous whitespace. "
        "Use a coherent composition with distinct primary and supporting areas, "
        "rather than enclosing every section or row in another bordered card. "
        "Lead with the result or activity that serves the user's main goal; keep "
        "supporting information and configuration secondary. "
        "Put optional preferences, notes and extra tips behind disclosures. "
        "The available canvas is commonly 700–1100px wide and fills the screen "
        "height; also make a genuinely usable 360px layout. Use responsive CSS "
        "based on the document width. Do not add another device toolbar, faux "
        "browser frame, output title bar or explanation of the UI itself. "
        "Every visible control must perform a useful local interaction; omit fake "
        "navigation, dead download buttons and decorative calls to action. "
        "Keep the implementation concise with shared styles and functions, rather "
        "than repeating large blocks of markup, so the complete document fits in one response. "
        "For bespoke themes use the custom palette consistently for page, text "
        "and controls; do not put --cb color tokens ahead of the custom colors "
        "as CSS fallbacks. On revision normalize older saved enum values to the "
        "new palette rather than leaving an unrecognized theme selected. "
        "Other resource requests are blocked by CSP. "
        "Never navigate the frame or request browser permissions; preventDefault on form submits. To revise "
        "an interface pass its artifact_id and the complete replacement HTML; keep state "
        "keys compatible. Previous revisions remain available in the output selector. "
        "Then send at most one brief usage sentence, "
        "not a duplicate question about values the user can already change in the interface. "
        "You cannot observe or change the user's saved preview state through this action."
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
