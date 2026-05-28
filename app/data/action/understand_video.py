from agent_core import action


@action(
    name="understand_video",
    description="Uses the configured VLM model (default: Gemini 1.5 Pro) for native video understanding when a Google API key is configured. Falls back to keyframe extraction via OpenCV if no Google API key is available.",
    mode="CLI",
    action_sets=["document_processing", "image", "video"],
    requirement=["google-genai"],
    input_schema={
        "video_path": {
            "type": "string",
            "example": "C:\\Users\\user\\Videos\\meeting.mp4",
            "description": "Absolute path to the video file (MP4, AVI, MOV supported).",
        },
        "query": {
            "type": "string",
            "example": "What is being presented on the slides?",
            "description": "Optional: specific question to answer about the video.",
        },
        "max_frames": {
            "type": "integer",
            "example": 8,
            "description": "Number of evenly-spaced keyframes to sample (default: 8, max recommended: 16).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if analysis completed, 'error' otherwise.",
        },
        "summary": {
            "type": "string",
            "example": "The video shows a person presenting slides about quarterly sales...",
            "description": "First 500 characters of the video summary. Full summary saved to file.",
        },
        "file_path": {
            "type": "string",
            "example": "/workspace/video_summary_20260414_153000.txt",
            "description": "Absolute path to the .txt file containing the full video summary.",
        },
        "file_saved": {
            "type": "boolean",
            "example": True,
            "description": "True if the full summary was saved to disk.",
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Error message if applicable.",
        },
    },
    test_payload={
        "video_path": "C:\\Users\\user\\Videos\\sample.mp4",
        "query": "Summarise the video content.",
        "max_frames": 8,
        "simulated_mode": True,
    },
)
def understand_video(input_data: dict) -> dict:
    import os

    video_path = str(input_data.get("video_path", "")).strip()
    query = str(input_data.get("query", "")).strip() or None
    max_frames = int(input_data.get("max_frames", 8))
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "summary": "The video shows a simulated presentation with 3 speakers.",
            "file_path": "/workspace/video_summary_simulated.txt",
            "file_saved": True,
            "message": "",
        }

    if not video_path:
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": "video_path is required.",
        }

    if not os.path.isfile(video_path):
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": "File not found.",
        }

    from app.config import get_api_key, get_vlm_model

    api_key = get_api_key("gemini")

    # --- Dual-path execution ---
    # This is the only video action that contains its own dispatch logic rather than
    # delegating entirely to InternalActionInterface. The reason is architectural:
    #
    # PATH 1 — Gemini Native (below, runs when api_key is present):
    #   Uses the Gemini Files API (client.files.upload) for true native video
    #   understanding. The full video is uploaded and processed by the model with
    #   temporal context — no frame sampling needed. The uploaded file is deleted
    #   from Gemini servers after the call. The full summary is saved to disk.
    #   This path is preferred: more accurate, handles long videos, no OpenCV dep.
    #
    # PATH 2 — OpenCV Keyframe Fallback (bottom of function):
    #   Used when no Gemini API key is configured, or if PATH 1 raises any exception.
    #   Delegates to InternalActionInterface.understand_video(), which extracts
    #   evenly-spaced keyframes using OpenCV and sends them to whatever VLM provider
    #   is currently configured. Results are returned directly without saving to disk.
    #
    # The Gemini Files API is not accessible through VLMInterface, which is why
    # this action cannot follow the standard single-delegation pattern.

    if api_key:
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            import time
            from datetime import datetime
            from app.config import AGENT_WORKSPACE_ROOT

            video_file = client.files.upload(file=video_path)

            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = client.files.get(name=video_file.name)

            vlm_model = get_vlm_model() or "gemini-1.5-pro"
            prompt = (
                query
                if query
                else "Understand and describe the contents of this video."
            )
            response = client.models.generate_content(
                model=vlm_model,
                contents=[video_file, prompt],
            )

            client.files.delete(name=video_file.name)

            full_text = response.text
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(AGENT_WORKSPACE_ROOT, f"video_summary_{ts}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            return {
                "status": "success",
                "summary": full_text[:500] + ("..." if len(full_text) > 500 else ""),
                "file_path": out_path,
                "file_saved": True,
                "message": "",
            }
        except Exception:
            # Fall through to fallback path if Gemini native path fails
            pass

    try:
        import app.internal_action_interface as iai

        result = iai.InternalActionInterface.understand_video(
            video_path, query=query, max_frames=max_frames
        )
        return {**result, "message": ""}
    except RuntimeError as e:
        # Catches missing opencv gracefully
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": str(e),
        }
