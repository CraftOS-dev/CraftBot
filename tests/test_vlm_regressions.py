"""Vision transport, error, OCR and async regressions without provider traffic."""

import asyncio
import base64
import io
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from agent_core.core.errors import ClassifiedError, ErrorCategory
from agent_core.core.impl.vlm.interface import VLMInterface


@pytest.fixture
def image_bytes():
    def make(fmt):
        output = io.BytesIO()
        Image.new("RGB", (32, 24), "red").save(output, format=fmt)
        return output.getvalue()

    return make


@pytest.fixture
def vision():
    """Use the public constructor but defer clients so no credentials are read."""
    iface = VLMInterface(provider="openai", model="gpt-4o-mini", deferred=True)
    iface._report_usage_async = Mock()
    iface.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content='{"shape":"square"}')
                            )
                        ],
                        usage=SimpleNamespace(
                            prompt_tokens=100,
                            completion_tokens=20,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=80),
                        ),
                    )
                )
            )
        )
    )
    return iface


@pytest.mark.parametrize(
    "fmt,mime",
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
    ],
)
def test_real_image_bytes_reach_sdk_with_matching_media_type(
    vision, image_bytes, fmt, mime
):
    raw = image_bytes(fmt)
    answer = vision.describe_image_bytes(
        raw, user_prompt="Return JSON describing the shape", log_response=False
    )
    assert answer == '{"shape":"square"}'
    call = vision.client.chat.completions.create.call_args.kwargs
    parts = call["messages"][-1]["content"]
    data_url = parts[1]["image_url"]["url"]
    prefix, encoded = data_url.split(",", 1)
    assert prefix == f"data:{mime};base64"
    assert base64.b64decode(encoded) == raw


@pytest.mark.parametrize(
    "provider",
    ["openai", "openrouter", "deepseek", "groq", "together", "lmstudio", "vllm"],
)
def test_openai_compatible_vision_routing_and_cache_accounting(
    vision, image_bytes, provider
):
    vision.provider = provider
    counter = [7]
    vision._get_token_count = lambda: counter[0]
    vision._set_token_count = lambda value: counter.__setitem__(0, value)
    vision.describe_image_bytes(image_bytes("PNG"), log_response=False)
    assert counter[0] == 47  # 7 + 100 prompt + 20 output - 80 cached
    vision._report_usage_async.assert_called_once_with(
        f"vlm_{provider}", provider, vision.model, 100, 20, 80
    )


def test_ocr_preserves_plain_text_and_does_not_force_json(
    vision, image_bytes, tmp_path
):
    image = tmp_path / "receipt.png"
    image.write_bytes(image_bytes("PNG"))
    vision.client.chat.completions.create.return_value.choices[
        0
    ].message.content = "TOTAL: 42.00\nPAID"
    assert vision.describe_image_ocr(str(image)) == "TOTAL: 42.00\nPAID"
    call = vision.client.chat.completions.create.call_args.kwargs
    assert "response_format" not in call
    assert "precise OCR engine" in call["messages"][0]["content"]


def test_default_description_satisfies_openai_json_mode_contract(vision, image_bytes):
    vision.describe_image_bytes(image_bytes("PNG"), log_response=False)
    call = vision.client.chat.completions.create.call_args.kwargs
    assert "response_format" not in call


@pytest.mark.parametrize("provider", ["openai", "groq", "lmstudio", "openrouter"])
def test_explicit_json_intent_supplies_instructions_and_validates_schema(
    vision, image_bytes, provider
):
    from agent_core.core.models.output import OutputIntent

    vision.provider = provider
    intent = OutputIntent(
        "json",
        {
            "type": "object",
            "required": ["shape"],
            "properties": {"shape": {"type": "string"}},
        },
    )
    assert vision.describe_image_bytes(
        image_bytes("PNG"), user_prompt="Identify it", output_intent=intent
    )
    call = vision.client.chat.completions.create.call_args.kwargs
    assert "JSON" in call["messages"][0]["content"]
    vision.client.chat.completions.create.return_value.choices[
        0
    ].message.content = '{"other": 1}'
    with pytest.raises(ClassifiedError):
        vision.describe_image_bytes(image_bytes("PNG"), output_intent=intent)


def test_legacy_explicit_json_mode_is_supported(vision, image_bytes):
    vision.describe_image_bytes(
        image_bytes("PNG"), user_prompt="Identify it", json_mode=True
    )
    call = vision.client.chat.completions.create.call_args.kwargs
    assert call["response_format"] == {"type": "json_object"}
    assert "JSON" in call["messages"][0]["content"]


@pytest.mark.parametrize("provider", ["remote", "byteplus"])
def test_http_vision_providers_report_normalized_usage(
    vision, image_bytes, monkeypatch, provider
):
    import agent_core.core.impl.vlm.interface as module

    vision.provider = provider
    vision.remote_url = vision.byteplus_base_url = "http://provider.invalid"
    vision.api_key = "synthetic"
    payload = (
        {"response": "Description", "prompt_eval_count": 50, "eval_count": 10}
        if provider == "remote"
        else {
            "choices": [{"message": {"content": "Description"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        }
    )
    monkeypatch.setattr(
        module.requests,
        "post",
        Mock(
            return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: payload
            )
        ),
    )
    assert (
        vision.describe_image_bytes(image_bytes("PNG"), log_response=False)
        == "Description"
    )
    assert vision._report_usage_async.call_count == 1
    assert vision._report_usage_async.call_args.args[:5] == (
        f"vlm_{provider}",
        provider,
        vision.model,
        50,
        10,
    )


@pytest.mark.parametrize("method", ["describe_image", "describe_image_ocr"])
def test_missing_image_fails_before_provider_call(vision, tmp_path, method):
    with pytest.raises(FileNotFoundError):
        getattr(vision, method)(str(tmp_path / "missing.png"))
    vision.client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize(
    "status,category",
    [
        (401, ErrorCategory.AUTH),
        (403, ErrorCategory.AUTH),
        (429, ErrorCategory.RATE_LIMIT),
        (500, ErrorCategory.SERVER),
    ],
)
def test_provider_http_errors_keep_actionable_classification(
    vision, image_bytes, status, category
):
    from openai import APIStatusError

    response = httpx.Response(
        status, request=httpx.Request("POST", "https://api.example.test/vision")
    )
    error = APIStatusError(
        "provider rejected request",
        response=response,
        body={"error": {"message": "provider rejected request"}},
    )
    vision.client.chat.completions.create.side_effect = error
    with pytest.raises(ClassifiedError) as caught:
        vision.describe_image_bytes(image_bytes("PNG"), log_response=False)
    assert caught.value.info.category == category
    vision._report_usage_async.assert_not_called()


def test_empty_choices_raise_a_classified_error(vision, image_bytes):
    vision.client.chat.completions.create.return_value.choices = []
    with pytest.raises(ClassifiedError):
        vision.describe_image_bytes(image_bytes("PNG"), log_response=False)


def test_async_vision_runs_sdk_off_the_event_loop(vision, image_bytes):
    caller_thread = threading.get_ident()
    sdk_threads = []
    response = vision.client.chat.completions.create.return_value

    def provider(**kwargs):
        sdk_threads.append(threading.get_ident())
        return response

    vision.client.chat.completions.create.side_effect = provider
    result = asyncio.run(
        vision.generate_response_async(
            image_bytes("PNG"), user_prompt="Describe the square", log_response=False
        )
    )
    assert result == '{"shape":"square"}'
    assert sdk_threads and sdk_threads[0] != caller_thread


def test_async_vision_delivers_usage_to_reporting_hook(vision, image_bytes):
    events = []

    async def report(event):
        events.append(event)

    vision._report_usage = report
    vision._report_usage_async = VLMInterface._report_usage_async.__get__(vision)

    async def run():
        await vision.generate_response_async(
            image_bytes("PNG"), user_prompt="Describe", log_response=False
        )
        await asyncio.sleep(0)

    asyncio.run(run())
    assert len(events) == 1
    assert events[0].input_tokens == 100
    assert events[0].cached_tokens == 80


def test_failed_reinitialization_returns_false_without_crashing(vision, monkeypatch):
    from app.models.factory import ModelFactory

    monkeypatch.setattr(
        ModelFactory, "create", Mock(side_effect=EnvironmentError("missing API key"))
    )
    assert vision.reinitialize(provider="openai", api_key="", base_url="") is False


def test_video_with_no_readable_frames_fails_before_provider(vision, tmp_path):
    pytest.importorskip("cv2")
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"")
    with pytest.raises(ValueError, match="frames|read"):
        vision.describe_video_frames(str(video))
    vision.client.chat.completions.create.assert_not_called()
