"""Synthetic transport/management boundaries; no real credentials or services."""

import hashlib
import json
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from app.credentials.browser_helper import HttpsFormLogin, _execute_form
from app.credentials.contracts import CredentialKind, HelperOperation
from app.credentials.host_service import ProtectedHost, metadata_page
from app.credentials.references import SourceReference, parse
from app.credentials.secrets import Secret
from app.credentials.use_errors import CredentialUseError


class ConsumerAdapterTests(unittest.TestCase):
    def test_references_are_canonical_identifiers_and_reject_ambiguous_versions(self):
        ref = SourceReference(uuid4(), uuid4(), 1)
        self.assertEqual(parse(ref.encode()), ref)
        for value in (
            ref.encode() + "?version=2",
            ref.encode().replace("/1", "/01"),
            "raw-source-value",
            "craftbot-vault://0/0/1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(value)

    def test_large_payload_is_bounded_ordered_and_immutable_after_completion(self):
        launch = SimpleNamespace(payload_text="", payload_ready=False, closed=Event())
        host = SimpleNamespace(leases={1: launch})
        body = json.dumps({"prompt": "synthetic context " * 8000})
        for offset in range(0, len(body), 8000):
            chunk = body[offset : offset + 8000]
            ProtectedHost._stage(
                host,
                launch,
                {
                    "offset": offset,
                    "data": chunk,
                    "done": offset + len(chunk) == len(body),
                },
            )
        self.assertTrue(launch.payload_ready)
        self.assertEqual(json.loads(launch.payload_text), json.loads(body))
        with self.assertRaises(CredentialUseError):
            ProtectedHost._stage(
                host, launch, {"offset": len(body), "data": " ", "done": True}
            )
        launch = SimpleNamespace(payload_text="", payload_ready=False, closed=Event())
        host = SimpleNamespace(leases={1: launch})
        for value in (
            {"offset": 1, "data": "{}", "done": True},
            {"offset": False, "data": "{}", "done": True},
            {"offset": 0, "data": "x" * 8001, "done": False},
            {"offset": 0, "data": "nonascii-é", "done": True},
        ):
            with self.subTest(value=value), self.assertRaises(CredentialUseError):
                ProtectedHost._stage(host, launch, value)

    def test_metadata_pages_are_bounded_and_do_not_skip_rows(self):
        rows = [
            {"credential_id": str(uuid4()), "account": "Visible label"}
            for _ in range(137)
        ]
        collected, offset = [], 0
        while True:
            page = metadata_page(rows, offset)
            self.assertLess(len(json.dumps(page)), 65536)
            collected.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual(collected, rows)
        with self.assertRaises(CredentialUseError):
            metadata_page(rows, -1)

    def test_invocation_stages_large_data_separately_from_executable_snapshot(self):
        from app.credentials.invocation import invoke

        ref = SourceReference(uuid4(), uuid4(), 1).encode()
        requests = []
        body = {"prompt": "large-context-marker " * 6000}

        def exchange(operation, **parameters):
            requests.append((operation, parameters))
            if operation == "launch":
                self.assertLess(len(parameters["files"]["call.py"]), 48000)
                self.assertNotIn("large-context-marker", parameters["files"]["call.py"])
                return {"run_id": "synthetic-run"}
            if operation == "result":
                return {
                    "response": {
                        "status": 200,
                        "content_type": "application/json",
                        "length": 2,
                    }
                }
            if operation == "response":
                return {"chunk": "{}"}
            return {}

        with patch("app.credentials.invocation.request", side_effect=exchange):
            self.assertEqual(
                invoke(ref, "model_openai", "chat_completions", body)["body"], "{}"
            )
        uploaded = "".join(p["data"] for op, p in requests if op == "stage_payload")
        self.assertEqual(json.loads(uploaded), body)
        self.assertEqual(requests[-1][0], "stop")
        self.assertIn(
            hashlib.sha256(uploaded.encode("ascii")).hexdigest(),
            requests[0][1]["files"]["call.py"],
        )

    def form(self):
        return HttpsFormLogin(
            HelperOperation("browser_example", "login"),
            CredentialKind.LOGIN,
            "https://example.test/login",
            login_page="https://example.test/sign-in",
            success_url="https://example.test/account",
            csrf_field="csrf",
            cookie_names=("__Host-session",),
        )

    def test_form_helper_exports_only_named_generated_cookies_and_rejects_echoes(self):
        spec = self.form()
        html = b'<form method="post" action="/login"><input name="username"><input name="password" type="password"><input name="csrf" type="hidden" value="nonce"></form>'
        fields = Secret(
            {
                "username": "private-login@example.test",
                "password": "synthetic-form-secret",
            }
        )
        final = Secret(
            [
                ("Location", "/account"),
                (
                    "Set-Cookie",
                    "__Host-session=generated-cookie; Secure; HttpOnly; Path=/",
                ),
            ]
        )
        with patch(
            "app.credentials.browser_helper._roundtrip",
            side_effect=[(200, Secret([]), Secret(html)), (302, final, Secret(b""))],
        ) as request:
            result = _execute_form(spec, fields, Mock(), {"body": None})
            self.assertEqual(
                json.loads(result.body)["cookies"][0]["value"], "generated-cookie"
            )
            self.assertNotIn("private-login", result.body)
            self.assertNotIn("synthetic-form-secret", result.body)
            self.assertEqual(request.call_args_list[-1].args[1], spec.endpoint)
        echo = Secret(
            [
                ("Location", "/account"),
                (
                    "Set-Cookie",
                    "__Host-session=synthetic-form-secret; Secure; HttpOnly; Path=/",
                ),
            ]
        )
        with patch(
            "app.credentials.browser_helper._roundtrip",
            side_effect=[(200, Secret([]), Secret(html)), (302, echo, Secret(b""))],
        ):
            with self.assertRaises(CredentialUseError):
                _execute_form(spec, fields, Mock(), None)

    def test_changed_form_action_cannot_receive_saved_values(self):
        html = b'<form method="post" action="https://other.test/login"><input name="username"><input name="password" type="password"></form>'
        with patch(
            "app.credentials.browser_helper._roundtrip",
            return_value=(200, Secret([]), Secret(html)),
        ) as request:
            with self.assertRaises(CredentialUseError):
                _execute_form(
                    self.form(),
                    Secret({"username": "private", "password": "synthetic"}),
                    Mock(),
                    None,
                )
            request.assert_called_once()


class SettingsAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_values_and_authority_operations_never_reach_owner_ipc(self):
        from app.credentials.settings import handle

        adapter, ws = Mock(), object()
        for data in (
            {"operation": "approve", "parameters": {}},
            {"operation": {}, "parameters": {}},
            {"operation": "entry", "parameters": {"password": "synthetic-raw-value"}},
        ):
            with patch("app.credentials.settings.request") as request:
                await handle(adapter, ws, data)
                request.assert_not_called()
                adapter._send_only_to.assert_called()
                adapter._broadcast.assert_not_called()
                self.assertFalse(adapter._send_only_to.call_args.args[1]["data"]["ok"])


class BrowserConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_generated_cookie_state_enters_existing_browser_context(self):
        from app.mini_browser.login import autofill

        context = SimpleNamespace(add_cookies=AsyncMock())
        page = SimpleNamespace(
            main_frame=SimpleNamespace(url="https://example.test/sign-in"),
            context=context,
            goto=AsyncMock(),
        )
        tab = SimpleNamespace(page=page, user_control=False)
        route = {
            "type": "form",
            "helper": "browser_example",
            "operation": "login",
            "endpoint": "https://example.test/login",
        }
        result = {
            "status": 200,
            "body": json.dumps(
                {
                    "cookies": [
                        {
                            "name": "__Host-session",
                            "value": "generated-cookie",
                            "url": "https://example.test/",
                            "secure": True,
                        }
                    ],
                    "continue_url": "https://example.test/account",
                }
            ),
        }
        reference = SourceReference(uuid4(), uuid4(), 1).encode()
        core = Mock()
        with (
            patch(
                "app.credentials.client.request",
                return_value={"helpers": [route], "more": False},
            ),
            patch("app.credentials.invocation.invoke", return_value=result),
        ):
            outcome = await autofill(
                core, tab, credential_reference=reference, helper="browser_example"
            )
        self.assertEqual(outcome["status"], "success")
        self.assertEqual(
            context.add_cookies.call_args.args[0][0]["value"], "generated-cookie"
        )
        core.vault.assert_not_called()
        page.goto.assert_awaited_once()

    async def test_navigation_change_and_exact_origin_aliases_invalidate_login(self):
        from app.mini_browser.login import autofill

        for changed in (True, False):
            with self.subTest(changed=changed):
                context = SimpleNamespace(add_cookies=AsyncMock())
                page = SimpleNamespace(
                    main_frame=SimpleNamespace(
                        url="https://example.test/sign-in"
                        if changed
                        else "https://example.test./sign-in"
                    ),
                    context=context,
                    goto=AsyncMock(),
                )
                tab = SimpleNamespace(page=page, user_control=False)
                route = {
                    "type": "form",
                    "helper": "browser_example",
                    "operation": "login",
                    "endpoint": "https://example.test/login",
                }

                def invoke(*args, **kwargs):
                    page.main_frame.url = "https://other.test/"
                    return {
                        "status": 200,
                        "body": json.dumps(
                            {
                                "cookies": [],
                                "continue_url": "https://example.test/account",
                            }
                        ),
                    }

                with (
                    patch(
                        "app.credentials.client.request",
                        return_value={"helpers": [route], "more": False},
                    ),
                    patch(
                        "app.credentials.invocation.invoke", side_effect=invoke
                    ) as use,
                ):
                    outcome = await autofill(
                        Mock(),
                        tab,
                        credential_reference=SourceReference(
                            uuid4(), uuid4(), 1
                        ).encode(),
                        helper="browser_example",
                    )
                self.assertEqual(outcome["outcome"], "owner_handoff_required")
                context.add_cookies.assert_not_called()
                if not changed:
                    use.assert_not_called()
