"""Bounded inline video understanding; ordinary file bytes, never vault values."""

import base64
import mimetypes
from pathlib import Path
from .references import parse
from .model_transport import requests_response


def analyse_video(reference, filename, model, prompt):
    parse(reference)
    path = Path(filename)
    media_type = mimetypes.guess_type(path.name)[0]
    if media_type not in (
        "video/mp4",
        "video/quicktime",
        "video/x-msvideo",
        "video/webm",
        "video/mpeg",
    ):
        raise ValueError("credential_video_format_unsupported")
    with path.open("rb") as source:
        data = source.read(23_000_001)
    if len(data) > 23_000_000:
        # The existing caller retains its keyframe fallback for larger inputs.
        raise ValueError("credential_video_input_limit")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": media_type,
                            "data": base64.b64encode(data).decode(),
                        }
                    },
                    {"text": prompt},
                ],
            }
        ]
    }
    response = requests_response(
        "gemini",
        reference,
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + model
        + ":generateContent",
        payload,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("promptFeedback", {}).get("blockReason"):
        raise ValueError("credential_video_no_content")
    for candidate in result.get("candidates", []):
        if candidate.get("finishReason") == "SAFETY":
            continue
        parts = (candidate.get("content") or {}).get("parts", [])
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()
        if text:
            return text
    raise ValueError("credential_video_no_content")
