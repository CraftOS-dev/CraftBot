from agent_core import action


@action(
    name="render_ui",
    description=(
        "Show an interactive HTML page in the output panel. Use it when "
        "manipulating inputs, comparing alternatives, inspecting changing data or tracking "
        "progress helps more than text (no UI request needed); otherwise answer in text and "
        "respect requested formats. Make it visually striking, not a plain form, list or table: "
        "build around a visual centerpiece (map, chart, diagram, SVG/canvas illustration, 3D "
        "scene or image), with bold typography, deliberate color, depth "
        "and motion for entrances and changes. All controls must work, by keyboard too. "
        "Inline CSS/JS only: no external scripts/CSS/fonts, on* attributes or secrets. Fill a "
        "responsive 360-900px wide, full-height page; the host shows the title. "
        "Colors must follow host light/dark: only --cb-{bg,surface,text,muted,border,accent,font} "
        "or light-dark(light,dark), not prefers-color-scheme; redraw canvas on window "
        "'craftbot-theme'. Static native input/select/textarea controls persist automatically: give "
        "each a stable id (or data-craftbot-state key). Use persistence='manual' for dynamic/custom "
        "canvas/3D/application state: restore window.craftbot.state and "
        "call window.craftbot.saveState(obj) on change (JSON, 64KB; store deadlines and "
        "timestamps). Fetched data needs loading/error states, real timestamps and checked "
        "units. Keep code compact. Afterwards send at most one short sentence; don't ask for "
        "values the page sets; you can't see its state."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "title": {
            "type": "string",
            "description": "Short title, up to 120 characters.",
        },
        "html": {
            "type": "string",
            "description": "Complete HTML document, up to 512 KB.",
        },
        "artifact_id": {
            "type": "string",
            "description": "Optional: earlier render_ui id in this session, to revise with complete new HTML (keep state keys).",
        },
        "persistence": {
            "type": "string",
            "description": "controls (default): persist static native controls by stable id/data-craftbot-state, hydrated before scripts run; manual: explicitly restore/save dynamic DOM or custom state with craftbot.state/saveState; none: stateless output. Never persist secrets.",
        },
        "libraries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional, preloaded as globals: leaflet (L; base map L.tileLayer.craftbot()), three (THREE, THREE.OrbitControls), chart (Chart.js), motion (Motion.animate/stagger/inView), lucide (lucide.createIcons() fills <i data-lucide=name>).",
        },
        "connect_origins": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional: up to 8 exact public HTTPS origins the page fetches (browser CORS, no keys).",
        },
        "image_origins": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional: up to 8 exact public HTTPS origins for web images.",
        },
        "images": {
            "type": "object",
            "description": "Optional: {name: local image path}, e.g. generate_image output; src = window.craftbot.images.name.",
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
    from app.generative_ui import make_artifact, read_images

    try:
        input_data = {"persistence": "controls", **input_data}
        artifact = make_artifact(input_data)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not input_data.get("simulated_mode", False):
        from app.internal_action_interface import InternalActionInterface as iai
        from app.usage.chat_storage import get_chat_storage

        try:
            images = await asyncio.to_thread(read_images, input_data.get("images", {}))
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
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
        artifact["images"] = await asyncio.to_thread(
            get_chat_storage().store_ui_images, session_id, artifact["id"], images
        )
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
