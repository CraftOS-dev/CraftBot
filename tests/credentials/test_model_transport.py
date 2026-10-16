"""Synthetic model adapters; no real SDK, network, Settings or token access."""

import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.credentials.client import CredentialHostUnavailable
from app.credentials.model_transport import VaultBedrockClient, VaultModelTransport
from app.credentials.references import SourceReference
from app.credentials.invocation import StaticResponse


class ModelTransportTests(unittest.TestCase):
    def setUp(self):
        self.reference = SourceReference(uuid4(), uuid4(), 1).encode()
        self.route = {
            "helper": "model_custom",
            "operation": "chat_completions",
            "method": "POST",
            "endpoint": "https://reviewed.example.test/v1/chat/completions",
            "type": "json",
        }

    def test_custom_endpoint_and_rotated_reference_use_exact_installed_policy(self):
        replacement = SourceReference(uuid4(), uuid4(), 2).encode()
        resolver = Mock(return_value=replacement)
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=[self.route],
            ),
            patch(
                "app.credentials.model_transport.open_response",
                return_value=StaticResponse(200, '{"result":"safe"}'),
            ) as invoke,
        ):
            transport = VaultModelTransport("custom", self.reference, resolver)
            request = httpx.Request(
                "POST", self.route["endpoint"], json={"model": "synthetic"}
            )
            response = transport.handle_request(request)
            response.read()
            self.assertEqual(response.json(), {"result": "safe"})
            self.assertEqual(
                invoke.call_args.args[:3],
                (replacement, "model_custom", "chat_completions"),
            )
            self.assertEqual(set(response.headers), {"content-type"})

    def test_redirect_query_and_unreviewed_destination_never_invoke(self):
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=[self.route],
            ),
            patch("app.credentials.model_transport.open_response") as invoke,
        ):
            transport = VaultModelTransport("custom", self.reference)
            for url in (
                self.route["endpoint"] + "?callback=elsewhere",
                "https://other.example.test/v1/chat/completions",
            ):
                with (
                    self.subTest(url=url),
                    self.assertRaises(CredentialHostUnavailable),
                ):
                    transport.handle_request(httpx.Request("POST", url, json={}))
            invoke.assert_not_called()

    def test_bedrock_keeps_model_region_and_binary_payload_in_existing_contract(self):
        route = {
            "helper": "model_bedrock",
            "operation": "fixed_converse",
            "method": "POST",
            "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com/model/synthetic.model:0/converse",
        }
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=[route],
            ),
            patch(
                "app.credentials.model_transport.invoke",
                return_value={
                    "status": 200,
                    "body": '{"output":{"message":{"content":[{"text":"safe"}]}}}',
                },
            ) as invoke,
        ):
            client = VaultBedrockClient(self.reference, "us-east-1")
            result = client.converse(
                modelId="synthetic.model:0",
                messages=[{"image": {"source": {"bytes": b"synthetic"}}}],
            )
            self.assertEqual(result["output"]["message"]["content"][0]["text"], "safe")
            self.assertNotIn("modelId", invoke.call_args.args[3])
            self.assertEqual(
                invoke.call_args.args[3]["messages"][0]["image"]["source"]["bytes"],
                "c3ludGhldGlj",
            )
            with self.assertRaises(CredentialHostUnavailable):
                client.converse(modelId="other.model:0", messages=[])
