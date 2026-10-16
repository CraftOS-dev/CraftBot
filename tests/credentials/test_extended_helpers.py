"""Synthetic route, media, OAuth, stream and cancellation checks; no live I/O."""

import base64
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.credentials.catalog import integration_helpers, model_helpers, specification
from app.credentials.contracts import CredentialKind, HelperOperation
from app.credentials.execution import OperationJob, OutputBudget
from app.credentials.helpers import (
    HelperRegistry,
    HttpsJsonOperation,
    JsonResult,
    _execute_json,
)
from app.credentials.route_policy import match_route, target
from app.credentials.secrets import Secret
from app.credentials.streaming import StreamFilter, relay
from app.credentials.use_errors import CredentialUseError, UseCode
from app.credentials.wire import encode
from test_broker import wire


class ExtendedHelperTests(unittest.TestCase):
    def setUp(self):
        self.spec = HttpsJsonOperation(
            HelperOperation("integration_test", "get"),
            CredentialKind.API_KEY,
            "https://reviewed.example.test/items/:item_id",
            method="GET",
            envelope=True,
            path_fields=("item_id",),
            query_fields=("limit",),
        )
        self.fields = Secret({"api_key": "SyntheticSource-8844-xyz"})

    def payload(self, **changes):
        return {
            "body": {
                "path": {"item_id": "item-123"},
                "query": {"limit": 5},
                "data": None,
                **changes,
            }
        }

    def test_entire_sealed_catalog_instantiates_without_runtime_provider_imports(self):
        rows = model_helpers() + integration_helpers()
        registry = HelperRegistry(tuple(specification(r) for r in rows))
        self.assertLessEqual(len(registry._entries), 1024)
        self.assertGreater(len(registry._entries), 800)

    def test_resource_templates_fix_host_method_and_parameter_grammar(self):
        route = dict(
            endpoint=self.spec.endpoint,
            method="GET",
            path_fields=["item_id"],
            query_fields=["limit"],
        )
        good = match_route(
            [route], "GET", "https://reviewed.example.test/items/item-123?limit=5"
        )
        self.assertEqual(good[1:], ({"item_id": "item-123"}, {"limit": "5"}))
        for url in (
            "https://attacker.test/items/item-123",
            "https://reviewed.example.test/items/..",
            "https://reviewed.example.test/items/%2e%2e",
            "https://reviewed.example.test/items/a%2Fb",
            "https://reviewed.example.test/items/a/b",
            "https://user@reviewed.example.test/items/id",
            "https://reviewed.example.test/items/id?callback=private",
            "https://reviewed.example.test/items/id?limit=1&limit=2",
        ):
            with self.subTest(url=url):
                self.assertIsNone(match_route([route], "GET", url))
        self.assertIsNone(
            match_route([route], "POST", "https://reviewed.example.test/items/id")
        )
        with self.assertRaises(ValueError):
            target(
                self.spec.endpoint,
                self.spec.path_fields,
                {"item_id": "https://attacker.test"},
            )

    def test_action_suffix_and_nested_repository_paths_round_trip(self):
        gemini = {
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/:model:generateContent",
            "method": "POST",
            "path_fields": ["model"],
        }
        self.assertEqual(
            match_route(
                [gemini],
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro:generateContent",
            )[1],
            {"model": "gemini-3-pro"},
        )
        path = target(
            "https://api.github.com/repos/:owner_repo/contents/:file_path",
            ("owner_repo", "file_path"),
            {"owner_repo": "owner/repo", "file_path": "folder/file.py"},
        )
        self.assertEqual(path, "/repos/owner/repo/contents/folder/file.py")

    def test_method_path_query_and_business_headers_are_host_controlled(self):
        with wire() as (connection, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = b'{"ok":true}'
            result = _execute_json(self.spec, self.fields, Mock(), self.payload())
            self.assertEqual(result.status, 200)
            self.assertEqual(
                connection.request.call_args.args[:2],
                ("GET", "/items/item-123?limit=5"),
            )
        for changes in (
            {"path": {"item_id": "../escape"}},
            {"query": {"callback": "http://127.0.0.1"}},
            {"headers": {"Authorization": "forged"}},
            {"headers": {"Host": "attacker.test"}},
        ):
            with wire() as (connection, *_), self.assertRaises(CredentialUseError):
                _execute_json(self.spec, self.fields, Mock(), self.payload(**changes))
            connection.request.assert_not_called()

    def test_multipart_carries_bytes_and_data_without_paths_or_supplied_filename(self):
        raw, mime = encode(
            {
                "fields": {"model": "image-test"},
                "files": [
                    {
                        "field": "image",
                        "content_type": "image/png",
                        "data": base64.b64encode(b"synthetic-png").decode(),
                    }
                ],
            },
            "multipart",
        )
        self.assertIn(b"synthetic-png", raw)
        self.assertIn(b'filename="upload.bin"', raw)
        self.assertTrue(mime.startswith("multipart/form-data; boundary=CraftBot"))
        for mime in ("text/html", "image/png\r\nAuthorization: evil"):
            with self.assertRaises(ValueError):
                encode(
                    {
                        "fields": {},
                        "files": [
                            {"field": "image", "content_type": mime, "data": "eA=="}
                        ],
                    },
                    "multipart",
                )

    def test_binary_download_filters_source_echo_and_preserves_safe_bytes(self):
        spec = replace(
            self.spec, response_format="binary", max_response_bytes=64_000_000
        )
        with wire() as (_, response, *_):
            response.getheader.return_value = "video/mp4"
            response.read.return_value = b"synthetic-video-bytes"
            result = _execute_json(spec, self.fields, Mock(), self.payload())
            self.assertEqual(
                base64.b64decode(json.loads(result.body)["data"]),
                b"synthetic-video-bytes",
            )
            response.read.return_value = (
                b"video-" + self.fields.reveal()["api_key"].encode()
            )
            with self.assertRaises(CredentialUseError):
                _execute_json(spec, self.fields, Mock(), self.payload())

    def test_oauth_form_injects_private_secret_and_returns_generated_tokens(self):
        spec = replace(
            self.spec,
            endpoint="https://reviewed.example.test/token",
            method="POST",
            path_fields=(),
            query_fields=(),
            protocol="oauth_form",
            request_format="form",
        )
        with wire() as (connection, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = b'{"access_token":"generated-access","refresh_token":"generated-refresh"}'
            result = _execute_json(
                spec,
                self.fields,
                Mock(),
                {
                    "body": {
                        "path": {},
                        "query": {},
                        "data": {
                            "client_id": "public-id",
                            "client_secret": "reference-only",
                            "refresh_token": "existing-refresh",
                        },
                    }
                },
            )
            from urllib.parse import parse_qs

            sent = parse_qs(connection.request.call_args.args[2].decode())
            self.assertEqual(sent["client_secret"], [self.fields.reveal()["api_key"]])
            self.assertEqual(sent["refresh_token"], ["existing-refresh"])
            self.assertNotIn("Authorization", connection.request.call_args.args[3])
            self.assertEqual(
                json.loads(result.body)["refresh_token"], "generated-refresh"
            )

    def test_basic_full_pair_and_header_encodings_never_return(self):
        spec = replace(
            self.spec,
            kind=CredentialKind.SERVICE_SECRET,
            secret_field="api_token",
            protocol="basic",
        )
        pair = "private-user:Synthetic-ApiToken-999"
        header = "Basic " + base64.b64encode(pair.encode()).decode()
        fields = Secret(
            {"username": "private-user", "api_token": "Synthetic-ApiToken-999"}
        )
        with wire() as (_, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = json.dumps(
                {
                    "pair": base64.b64encode(pair.encode()).decode(),
                    "header": base64.b64encode(header.encode()).decode(),
                }
            ).encode()
            result = _execute_json(spec, fields, Mock(), self.payload())
            self.assertNotIn(base64.b64encode(pair.encode()).decode(), result.body)
            self.assertNotIn(base64.b64encode(header.encode()).decode(), result.body)


class StreamingTests(unittest.TestCase):
    def frame(self, text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})

    def test_first_safe_event_is_released_before_end_of_stream(self):
        out = []
        filtering = StreamFilter(
            Secret({"api_key": "SyntheticSource-xyz-987"}), out.append
        )
        filtering.feed(self.frame("Hello!"))
        self.assertEqual(len(out), 1)
        filtering.feed("data: [DONE]")
        self.assertTrue(out[-1].startswith("data: [DONE]"))

    def test_split_literal_and_common_encoded_echo_never_releases_first_fragment(self):
        source = "SyntheticSource-xyz-987"
        for value in (
            source,
            base64.b64encode(source.encode()).decode(),
            source.encode().hex(),
        ):
            out = []
            filtering = StreamFilter(Secret({"api_key": source}), out.append)
            middle = len(value) // 2
            filtering.feed(self.frame(value[:middle]))
            self.assertEqual(out, [])
            with self.assertRaises(CredentialUseError):
                filtering.feed(self.frame(value[middle:]))
            self.assertEqual(out, [])

    def test_utf8_crlf_and_cancel_are_checked_incrementally(self):
        raw = (self.frame("Hello café!") + "\r\n\r\ndata: [DONE]\r\n\r\n").encode()
        response = SimpleNamespace(
            read1=Mock(side_effect=[bytes([b]) for b in raw] + [b""])
        )
        execution = SimpleNamespace(cancelled=Event(), emit=Mock())
        relay(
            response, Secret({"api_key": "SyntheticSource-xyz-987"}), execution, 10000
        )
        self.assertIn("café", execution.emit.call_args_list[0].args[0])
        execution.cancelled.set()
        with self.assertRaises(CredentialUseError) as error:
            relay(
                response,
                Secret({"api_key": "SyntheticSource-xyz-987"}),
                execution,
                10000,
            )
        self.assertEqual(error.exception.code, UseCode.INTERRUPTED)

    def test_jobs_release_aggregate_quota_on_close_and_cancel_coarsely(self):
        budget = OutputBudget(10)
        first = OperationJob(
            lambda job: JsonResult(200, "12345678", "application/json"), budget=budget
        )
        first.thread.start()
        first.thread.join(1)
        self.assertEqual(budget.used, 8)
        second = OperationJob(
            lambda job: JsonResult(200, "12345678", "application/json"), budget=budget
        )
        second.thread.start()
        second.thread.join(1)
        self.assertEqual(second.snapshot()["error"], UseCode.LIMIT.value)
        first.close()
        self.assertEqual(budget.used, 0)
        cancelled = OperationJob(
            lambda job: (_ for _ in ()).throw(RuntimeError("private-network-error"))
        )
        cancelled.cancelled.set()
        cancelled.thread.start()
        cancelled.thread.join(1)
        self.assertEqual(cancelled.snapshot()["error"], UseCode.INTERRUPTED.value)
        self.assertNotIn("private-network-error", str(cancelled.snapshot()))

    def test_async_json_dispatch_releases_reservation_before_response_wait(self):
        from test_broker import CredentialBrokerTests

        case = CredentialBrokerTests()
        case.setUp()
        try:
            spec = HttpsJsonOperation(
                HelperOperation("integration_test", "query"),
                CredentialKind.API_KEY,
                "https://example.test/query",
            )
            case.broker._registry = HelperRegistry((spec,))
            grant = case.broker.approve(
                case.context, case.reference, spec.operation, payload={"body": {}}
            )
            capability = case.broker.authorize(case.context, grant.grant_id)
            with wire() as (_, response, *_):
                response.getheader.return_value = "application/json"
                response.read.return_value = b"{}"

                def after_send():
                    # A second thread can now acquire broker/vault locks while
                    # the response is still being read in this helper thread.
                    from concurrent.futures import ThreadPoolExecutor

                    with ThreadPoolExecutor(1) as pool:
                        self.assertEqual(
                            pool.submit(case.vault.list_items)
                            .result(1)[0]
                            .summary.reference,
                            case.reference,
                        )
                    return response

                with patch(
                    "app.credentials.helpers.http.client.HTTPSConnection"
                ) as cls:
                    connection = cls.return_value
                    connection.getresponse.side_effect = after_send
                    case.broker.execute(case.context, capability, {"body": {}})
        finally:
            case.tearDown()
