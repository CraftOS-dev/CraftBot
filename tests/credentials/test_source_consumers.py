"""Normal integration shaping and generated-token transport stay outside vault."""

import asyncio
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.credentials.integrations import RoutedSourceClient
from app.credentials.references import SourceReference
from app.credentials.client import CredentialHostUnavailable
from craftos_integrations.config import ConfigStore
from craftos_integrations.helpers.http import request, raw_request


class SourceConsumerTests(unittest.TestCase):
    def setUp(self):
        self.ref = SourceReference(uuid4(), uuid4(), 1).encode()

    def test_original_client_transforms_provider_output_with_placeholder_only(self):
        built = []

        class Client:
            def __init__(self, credential):
                self.credential = credential

            def read(self, identifier):
                return request(
                    "GET",
                    "https://reviewed.example.test/items/" + identifier,
                    headers={
                        "Authorization": "Bearer " + self.credential["access_token"]
                    },
                    transform=lambda body: {"title": body["name"].upper()},
                )

        def build(data, persist):
            built.append(data)
            return Client(data)

        provider = SimpleNamespace(id="synthetic", build_client=build)
        route = dict(
            helper="integration_synthetic",
            operation="read",
            method="GET",
            endpoint="https://reviewed.example.test/items/:item_id",
            path_fields=["item_id"],
            query_fields=[],
            envelope=True,
        )
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=[route],
            ),
            patch(
                "app.credentials.integrations.invoke",
                return_value={
                    "status": 200,
                    "body": '{"name":"safe"}',
                    "content_type": "application/json",
                },
            ) as invoke,
            patch("craftos_integrations.helpers.http.httpx.request") as ordinary,
        ):
            client = RoutedSourceClient(
                provider, self.ref, {"user_id": "public-metadata"}
            )
            result = client.read("id-123")
        ordinary.assert_not_called()
        self.assertEqual(result, {"ok": True, "result": {"title": "SAFE"}})
        self.assertEqual(built[0]["access_token"], "vault-managed")
        self.assertEqual(
            invoke.call_args.args[:3], (self.ref, "integration_synthetic", "read")
        )
        self.assertEqual(invoke.call_args.args[3]["path"], {"item_id": "id-123"})
        self.assertNotIn("Authorization", json.dumps(invoke.call_args.args))

    def test_oauth_reference_body_and_basic_header_never_reach_ordinary_network(self):
        for basic in (False, True):
            body = {"grant_type": "refresh_token", "refresh_token": "existing-refresh"}
            headers = {}
            if basic:
                headers["Authorization"] = (
                    "Basic "
                    + base64.b64encode(("public-id:" + self.ref).encode()).decode()
                )
            else:
                body.update(client_id="public-id", client_secret=self.ref)
            hook = Mock(
                return_value=httpx.Response(200, json={"access_token": "generated-new"})
            )
            with (
                patch.dict(
                    ConfigStore.extras, {"source_oauth_request": hook}, clear=True
                ),
                patch("craftos_integrations.helpers.http.httpx.request") as network,
            ):
                result = request(
                    "POST",
                    "https://oauth2.googleapis.com/token",
                    data=body,
                    headers=headers,
                    expected=(200,),
                )
            network.assert_not_called()
            self.assertEqual(result["result"]["access_token"], "generated-new")
            self.assertEqual(hook.call_args.kwargs["reference"], self.ref)
            self.assertEqual(
                hook.call_args.kwargs["body"]["refresh_token"], "existing-refresh"
            )
            self.assertEqual(hook.call_args.kwargs["basic"], basic)

    def test_missing_oauth_reference_hook_fails_closed_and_generated_access_stays_direct(
        self,
    ):
        with (
            patch.dict(ConfigStore.extras, {}, clear=True),
            patch("craftos_integrations.helpers.http.httpx.request") as network,
        ):
            result = request(
                "POST",
                "https://oauth2.googleapis.com/token",
                data={"client_secret": self.ref},
            )
            self.assertIn("credential_oauth_helper_unavailable", result["error"])
            network.assert_not_called()
            network.return_value = httpx.Response(200, json={"messages": []})
            result = request(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": "Bearer existing-access"},
            )
            self.assertEqual(result["result"], {"messages": []})
            network.assert_called_once()

    def test_approved_exchange_uses_installed_endpoint_only(self):
        from app.credentials.oauth_transport import request as exchange

        route = dict(
            helper="oauth_google",
            operation="exchange",
            endpoint="https://oauth2.googleapis.com/token",
            method="POST",
            protocol="oauth_form",
        )
        with (
            patch(
                "app.credentials.oauth_transport.installed_model_helpers",
                return_value=[route],
            ),
            patch(
                "app.credentials.oauth_transport.invoke",
                return_value={"status": 200, "body": '{"access_token":"generated"}'},
            ) as invoke,
        ):
            response = exchange(
                "POST",
                route["endpoint"],
                reference=self.ref,
                body={"client_secret": self.ref, "refresh_token": "existing"},
            )
            self.assertEqual(response.json(), {"access_token": "generated"})
            self.assertNotIn("client_secret", invoke.call_args.args[3]["data"])
            with self.assertRaises(CredentialHostUnavailable):
                exchange(
                    "POST", "https://attacker.test/token", reference=self.ref, body={}
                )
            self.assertEqual(invoke.call_count, 1)

    def test_cancelled_coroutine_propagates_without_resolving_any_source(self):
        from app.credentials.invocation import invoke_async
        from threading import Event

        seen = Event()

        def execute(*args, cancelled, **kwargs):
            cancelled.wait(2)
            if cancelled.is_set():
                seen.set()
            raise CredentialHostUnavailable("credential_use_interrupted")

        async def exercise():
            with patch("app.credentials.invocation.invoke", side_effect=execute):
                task = asyncio.create_task(
                    invoke_async(self.ref, "model_test", "chat", {})
                )
                await asyncio.sleep(0.02)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.to_thread(seen.wait, 2)

        asyncio.run(exercise())
        self.assertTrue(seen.is_set())

    def test_unauthenticated_generated_upload_url_keeps_original_transport(self):
        from craftos_integrations.helpers.source_requests import using

        source = Mock()
        with (
            using(source),
            patch(
                "craftos_integrations.helpers.http.httpx.request",
                return_value=httpx.Response(200),
            ) as network,
        ):
            raw_request(
                "POST",
                "https://uploads.example.test/generated-session",
                content=b"synthetic-bytes",
            )
        source.assert_not_called()
        network.assert_called_once()

    def test_bounded_inline_video_uses_helper_without_a_google_sdk_key(self):
        from app.credentials.media_clients import analyse_video
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            filename = Path(temporary) / "synthetic.mp4"
            filename.write_bytes(b"synthetic-video")
            response = httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": "Video summary"}]}}]
                },
                request=httpx.Request("POST", "https://reviewed.example.test"),
            )
            with patch(
                "app.credentials.media_clients.requests_response", return_value=response
            ) as execute:
                result = analyse_video(
                    self.ref, filename, "gemini-example", "Describe this video"
                )
            self.assertEqual(result, "Video summary")
            self.assertEqual(execute.call_args.args[1], self.ref)
            payload = execute.call_args.args[4]
            self.assertEqual(
                base64.b64decode(
                    payload["contents"][0]["parts"][0]["inlineData"]["data"]
                ),
                b"synthetic-video",
            )
            self.assertNotIn(str(filename), json.dumps(payload))

    def test_audio_reference_cannot_fall_through_to_a_raw_sdk_constructor(self):
        from craftos_integrations.providers.discord import _discord_voice as voice

        factory = Mock(return_value=object())
        with (
            patch.dict(
                ConfigStore.extras, {"openai_client_factory": factory}, clear=True
            ),
            patch.object(voice, "OpenAI", create=True) as sdk,
        ):
            self.assertIs(voice._audio_client(self.ref), factory.return_value)
            sdk.assert_not_called()

        with (
            patch.dict(ConfigStore.extras, {}, clear=True),
            patch.object(voice, "OpenAI", create=True) as sdk,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "credential_audio_helper_unavailable"
            ):
                voice._audio_client(self.ref)
            sdk.assert_not_called()

    def test_whatsapp_public_account_selection_is_verified_without_accepting_source_fields(
        self,
    ):
        from app.credentials.integrations import SavedSourceOperations

        spi = SavedSourceOperations([SimpleNamespace(id="whatsapp_business")])
        routes = [
            {
                "helper": "integration_whatsapp_business",
                "operation": "verify",
                "endpoint": "https://graph.facebook.com/v21.0/:phone_number_id",
            }
        ]
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=routes,
            ),
            patch(
                "app.credentials.integrations.invoke",
                return_value={"status": 200, "body": '{"id":"12345678"}'},
            ) as execute,
        ):
            identity, metadata = spi.connect(
                "whatsapp_business",
                self.ref,
                public_metadata={"phone_number_id": "12345678"},
            )
            self.assertEqual(identity, "12345678")
            self.assertEqual(metadata["phone_number_id"], identity)
            self.assertEqual(
                execute.call_args.args[3]["path"], {"phone_number_id": identity}
            )
            for data in (
                {"phone_number_id": "https://attacker.test"},
                {"phone_number_id": "12345678", "access_token": "raw-value"},
            ):
                with (
                    self.subTest(data=data),
                    self.assertRaises(CredentialHostUnavailable),
                ):
                    spi.connect("whatsapp_business", self.ref, public_metadata=data)
            self.assertEqual(execute.call_count, 1)
