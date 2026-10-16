"""Synthetic authentication support; never install/start a service or use accounts."""

import asyncio
import ast
import base64
import copy
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import unquote
from uuid import uuid4
from pathlib import Path

from app.credentials.catalog import (
    authentication_helpers,
    integration_helpers,
    specification,
)
from app.credentials.helpers import _execute_json
from app.credentials.integrations import RoutedSourceClient, SavedSourceOperations
from app.credentials.migration import (
    migrate_environment_document,
    migrate_integration_document,
)
from app.credentials.mtproto_helper import DC_ADDRESSES, validate
from app.credentials.references import SourceReference, is_reference
from app.credentials.secrets import Secret
from app.credentials.twitter_helper import authorization
from app.credentials.use_errors import CredentialUseError
from craftos_integrations.config import ConfigStore
from craftos_integrations.helpers.source_auth import telegram_session_client
from craftos_integrations.providers._lark_common import (
    LarkCredential,
    ensure_token,
    validate_and_mint_token,
)
from craftos_integrations.providers.telegram_user import _telegram_mtproto
import test_broker
import test_source_migration


def route(helper, operation):
    return specification(
        next(
            r
            for r in authentication_helpers()
            if r["helper"] == helper and r["operation"] == operation
        )
    )


class AuthenticationTests(TestCase):
    def setUp(self):
        self.ref = SourceReference(uuid4(), uuid4(), 1).encode()
        self.addCleanup(setattr, ConfigStore, "extras", ConfigStore.extras)
        ConfigStore.extras = {}

    def test_oauth1_published_reference_vector(self):
        fields = Secret(
            {"api_key": "dpf43f3p2l4k3l03", "api_secret": "kd94hf93k423kf44"}
        )
        session = {
            "access_token": "nnch734d00sl2jdk",
            "access_token_secret": "pfkkdhi9sl3r4s00",
        }
        with (
            patch(
                "app.credentials.twitter_helper.secrets.token_hex",
                return_value="kllo9940pd9333jh",
            ),
            patch("app.credentials.twitter_helper.time.time", return_value=1191242096),
        ):
            header, _ = authorization(
                "http://photos.example.net/photos",
                "GET",
                "file=vacation.jpg&size=original",
                fields,
                session,
            )
        values = dict(
            (k, unquote(v.strip('"')))
            for k, v in (part.split("=", 1) for part in header.reveal()[6:].split(", "))
        )
        self.assertEqual(values["oauth_signature"], "tR3+Ty81lMeYAr/Fid0kMTYa/WM=")

    def test_twitter_fixed_send_scrubs_app_and_session_auth_echoes(self):
        spec = route("integration_twitter", "verify")
        fields = Secret(
            {"api_key": "synthetic-consumer-447", "api_secret": "synthetic-secret-581"}
        )
        session = {
            "access_token": "generated-token-123",
            "access_token_secret": "generated-secret-456",
        }
        with test_broker.wire() as (connection, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = json.dumps(
                {
                    "echo": base64.b64encode(
                        fields.reveal()["api_secret"].encode()
                    ).decode(),
                    "token": session["access_token_secret"],
                }
            ).encode()
            result = _execute_json(
                spec,
                fields,
                Mock(),
                {"body": {"path": {}, "query": {}, "data": None, "session": session}},
            )
            self.assertEqual(
                connection.request.call_args.args[:2], ("GET", "/2/users/me")
            )
            self.assertTrue(
                connection.request.call_args.args[3]["Authorization"].startswith(
                    "OAuth "
                )
            )
            self.assertNotIn("synthetic-secret", result.body)
            self.assertNotIn("generated-secret", result.body)
            self.assertIn("[redacted]", result.body)

    def test_twitter_missing_session_wrong_origin_and_forged_oauth_query_fail(self):
        spec = route("integration_twitter", "verify")
        with self.assertRaises(ValueError):
            replace(spec, endpoint="https://attacker.example/2/users/me")
        for session in (
            None,
            {},
            {"access_token": "x", "access_token_secret": "y", "api_secret": "z"},
        ):
            with (
                test_broker.wire() as (connection, *_),
                self.assertRaises(CredentialUseError),
            ):
                _execute_json(
                    spec,
                    Secret(
                        {"api_key": "synthetic-key", "api_secret": "synthetic-secret"}
                    ),
                    Mock(),
                    {
                        "body": {
                            "path": {},
                            "query": {},
                            "data": None,
                            "session": session,
                        }
                    },
                )
            connection.request.assert_not_called()

    def test_original_twitter_client_uses_fixed_routes_and_preserves_token_pair(self):
        from craftos_integrations.providers.twitter.provider import TwitterProvider

        metadata = {
            "access_token": "existing-user-token",
            "access_token_secret": "existing-user-secret",
            "user_id": "123",
        }
        with (
            patch(
                "app.credentials.model_transport.installed_model_helpers",
                return_value=integration_helpers(),
            ),
            patch(
                "app.credentials.integrations.invoke",
                return_value={
                    "status": 200,
                    "body": '{"data":{"id":"123","username":"user"}}',
                    "content_type": "application/json",
                },
            ) as invoke,
        ):
            client = RoutedSourceClient(TwitterProvider(), self.ref, metadata)
            result = asyncio.run(client.get_me())
        self.assertEqual(result["result"]["id"], "123")
        self.assertEqual(
            invoke.call_args.args[3]["session"],
            {k: metadata[k] for k in ("access_token", "access_token_secret")},
        )
        self.assertEqual(client.client._cred.api_secret, "vault-managed")

    def test_twitter_connect_stores_generated_pair_with_verified_identity(self):
        metadata = {
            "access_token": "existing-access",
            "access_token_secret": "existing-secret",
        }
        with patch(
            "app.credentials.integrations.invoke",
            return_value={
                "status": 200,
                "body": '{"data":{"id":"123","username":"owner"}}',
            },
        ):
            identity, result = SavedSourceOperations().connect(
                "twitter", self.ref, public_metadata=metadata
            )
        self.assertEqual(identity, "123")
        self.assertEqual(result["access_token_secret"], metadata["access_token_secret"])
        self.assertNotIn("api_secret", result)

    def test_lark_injects_secret_only_at_fixed_token_and_websocket_exchanges(self):
        for operation, expected in (
            ("tenant_token", {"app_id", "app_secret"}),
            ("websocket_endpoint", {"AppID", "AppSecret"}),
        ):
            with (
                self.subTest(operation=operation),
                test_broker.wire() as (connection, response, *_),
            ):
                response.getheader.return_value = "application/json"
                response.read.return_value = (
                    b'{"code":0,"tenant_access_token":"new-generated-token"}'
                )
                result = _execute_json(
                    route("auth_lark", operation),
                    Secret({"api_key": "synthetic-lark-secret"}),
                    Mock(),
                    {"body": {"app_id": "cli_123"}},
                )
                sent = json.loads(connection.request.call_args.args[2])
                self.assertEqual(set(sent), expected)
                self.assertNotIn("Authorization", connection.request.call_args.args[3])
                self.assertIn("new-generated-token", result.body)

    def test_lark_consumers_refresh_same_cache_with_reference_only(self):
        ConfigStore.extras["source_lark_request"] = Mock(
            return_value={
                "code": 0,
                "tenant_access_token": "generated-new",
                "expire": 7200,
            }
        )
        cred = LarkCredential(
            app_id="cli_123",
            app_secret=self.ref,
            tenant_access_token="expired",
            token_expires_at=0,
        )
        with (
            patch("craftos_integrations.providers._lark_common.http_request") as raw,
            patch(
                "craftos_integrations.providers._lark_common.save_credential"
            ) as persist,
        ):
            self.assertEqual(ensure_token(cred, "synthetic.json"), "generated-new")
        raw.assert_not_called()
        persist.assert_called_once_with("synthetic.json", cred)
        self.assertEqual(cred.app_secret, self.ref)

    def test_lark_missing_hook_fails_before_network(self):
        with (
            patch("craftos_integrations.providers._lark_common.http_request") as raw,
            self.assertRaises(RuntimeError),
        ):
            validate_and_mint_token("cli_123", self.ref)
        raw.assert_not_called()

    def test_lark_websocket_sdk_contains_placeholder_and_gets_generated_url(self):
        from craftos_integrations.helpers.source_auth import lark_ws_client

        class SDK:
            def __init__(self, app_id, app_secret, **kw):
                self.secret = app_secret

            def _configure(self, config):
                self.config = config

        ConfigStore.extras["source_lark_request"] = Mock(
            return_value={
                "code": 0,
                "data": {"URL": "wss://msg-frontier.larksuite.com/ws?token=generated"},
            }
        )
        client = lark_ws_client(SDK, "cli_123", self.ref)
        self.assertEqual(client.secret, "vault-managed")
        self.assertTrue(
            client._get_conn_url().startswith("wss://msg-frontier.larksuite.com/")
        )
        ConfigStore.extras["source_lark_request"].return_value = {
            "code": 0,
            "data": {"URL": "wss://attacker.example/ws"},
        }
        with self.assertRaises(RuntimeError):
            client._get_conn_url()

    def test_mtproto_reference_auth_never_constructs_consumer_sdk(self):
        hook = AsyncMock(
            return_value={"ok": True, "result": {"session_string": "generated-session"}}
        )
        ConfigStore.extras["source_telegram_auth"] = hook
        with patch.object(_telegram_mtproto, "TelegramClient") as sdk:
            result = asyncio.run(
                _telegram_mtproto.start_auth(123, self.ref, "+123456789")
            )
        sdk.assert_not_called()
        self.assertEqual(result["result"]["session_string"], "generated-session")
        hook.assert_awaited_once_with(
            "send_code", "123", self.ref, phone_number="+123456789"
        )

    def test_mtproto_missing_hook_and_private_auth_context_fail_closed(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(_telegram_mtproto.start_auth(123, self.ref, "+123456789"))

        async def forbidden():
            async with _telegram_mtproto._client_for_auth(123, self.ref):
                pass

        with self.assertRaises(RuntimeError):
            asyncio.run(forbidden())

    def test_mtproto_never_accepts_plaintext_password_for_saved_auth(self):
        ConfigStore.extras["source_telegram_auth"] = AsyncMock()
        result = asyncio.run(
            _telegram_mtproto.complete_auth(
                123,
                self.ref,
                "+123456789",
                "12345",
                "hash",
                password="must-not-forward",
            )
        )
        self.assertIn("vault", result["error"])
        ConfigStore.extras["source_telegram_auth"].assert_not_called()

    def test_mtproto_input_cannot_select_host_proxy_method_or_path(self):
        base = {"api_id": "123", "phone_number": "+123456789"}
        validate("send_code", base)
        for extra in (
            {"host": "127.0.0.1"},
            {"proxy": "http://attacker.example"},
            {"method": "deleteAccount"},
            {"api_id": True},
            {"phone_number": "../bad"},
        ):
            with self.subTest(extra=extra), self.assertRaises(CredentialUseError):
                validate("send_code", {**base, **extra})

    def test_existing_session_has_no_hash_and_never_prompts_on_expiry(self):
        class SDK:
            def __init__(self, session, api_id, api_hash):
                self.args = (session, api_id, api_hash)
                self.connect, self.disconnect = AsyncMock(), AsyncMock()
                self.is_user_authorized = AsyncMock(return_value=False)

        client = telegram_session_client(SDK, "existing-session", 123, "vault-managed")
        with self.assertRaises(RuntimeError):
            asyncio.run(client.start())
        self.assertEqual(client.args, ("existing-session", 123, "vault-managed"))
        client.disconnect.assert_awaited_once()

    def test_host_mtproto_pins_session_destination_and_suppresses_sdk_logs(self):
        from telethon.sessions import StringSession
        from telethon.crypto import AuthKey
        from app.credentials.mtproto_helper import execute

        session = StringSession()
        session.set_dc(2, "127.0.0.1", 4444)
        session.auth_key = AuthKey(b"x" * 256)
        created = []

        class Client:
            def __init__(self, received, api_id, api_hash, **kwargs):
                created.append((received, api_id, api_hash, kwargs))
                self.session = received
                self.connect, self.disconnect = AsyncMock(), AsyncMock()
                self.send_code_request = AsyncMock(
                    return_value=SimpleNamespace(phone_code_hash="generated-hash")
                )
                self.sign_in = AsyncMock()
                self.get_me = AsyncMock(
                    return_value=SimpleNamespace(
                        id=123,
                        first_name="Owner",
                        last_name="",
                        username="owner",
                        phone="123456789",
                    )
                )

        body = {
            "api_id": "123",
            "phone_number": "+123456789",
            "code": "12345",
            "phone_code_hash": "hash",
            "session_string": session.save(),
        }
        with patch("telethon.TelegramClient", Client):
            result = execute(
                route("auth_telegram_user", "complete"),
                Secret({"api_hash": "a" * 32}),
                Mock(),
                {"body": body},
                None,
                Mock(),
            )
        self.assertTrue(json.loads(result.body)["ok"])
        received, _, _, kwargs = created[0]
        self.assertEqual(
            (received.server_address, received.port), (DC_ADDRESSES[2], 443)
        )
        logger = kwargs["base_logger"]
        self.assertIs(logger.getChild("network"), logger)
        self.assertTrue(logger.disabled)
        self.assertIsNone(kwargs["proxy"])
        self.assertFalse(kwargs["auto_reconnect"])
        connection = kwargs["connection"](
            "127.0.0.1", 443, 99, loggers=Mock(__getitem__=Mock(return_value=logger))
        )
        with self.assertRaises(CredentialUseError):
            asyncio.run(connection._connect())
        from telethon.network.connection import ConnectionTcpFull

        connection = kwargs["connection"](
            "127.0.0.1", 4444, 5, loggers=Mock(__getitem__=Mock(return_value=logger))
        )
        with patch.object(ConnectionTcpFull, "_connect", new_callable=AsyncMock):
            asyncio.run(connection._connect())
        self.assertEqual((connection._ip, connection._port), (DC_ADDRESSES[5], 443))

    def test_host_mtproto_cancellation_disconnects_before_return(self):
        from app.credentials.mtproto_helper import execute

        disconnected = AsyncMock()

        async def wait_connect():
            await asyncio.sleep(20)

        class Client:
            def __init__(self, *args, **kwargs):
                self.connect, self.disconnect = (
                    AsyncMock(side_effect=wait_connect),
                    disconnected,
                )

        execution = SimpleNamespace(cancelled=Event())
        execution.cancelled.set()
        with (
            patch("telethon.TelegramClient", Client),
            self.assertRaises(CredentialUseError),
        ):
            execute(
                route("auth_telegram_user", "send_code"),
                Secret({"api_hash": "b" * 32}),
                Mock(),
                {"body": {"api_id": "123", "phone_number": "+123456789"}},
                execution,
                Mock(),
            )
        disconnected.assert_awaited_once()

    def test_saved_connect_flows_persist_generated_lark_token_and_telegram_session(
        self,
    ):
        from craftos_integrations.providers.lark_calendar.provider import (
            LarkCalendarProvider,
        )
        from craftos_integrations.providers.telegram_user.provider import (
            TelegramUserProvider,
        )
        from craftos_integrations.providers.telegram_user.client import (
            _pending_telegram_auth,
        )

        source = Path("app/data/action/integrations/_helpers.py").read_text(
            encoding="utf-8"
        )
        function = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "system_connect_token"
        )
        namespace = {"Dict": dict}
        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]),
                "<connect function>",
                "exec",
            ),
            namespace,
        )
        connect = namespace["system_connect_token"]
        system = SimpleNamespace(
            _require_provider=Mock(return_value=LarkCalendarProvider()),
            store_credential=Mock(),
        )
        ConfigStore.extras["source_lark_request"] = Mock(
            return_value={
                "code": 0,
                "tenant_access_token": "generated-lark",
                "expire": 7200,
            }
        )
        self.assertTrue(
            connect(
                system,
                "lark_calendar",
                {"source_reference": self.ref, "app_id": "cli_123"},
            )[0]
        )
        stored = system.store_credential.call_args.args[2]
        self.assertEqual(stored["app_secret"], self.ref)
        self.assertEqual(stored["tenant_access_token"], "generated-lark")
        system._require_provider.return_value = TelegramUserProvider()
        ConfigStore.extras["source_telegram_auth"] = AsyncMock(
            side_effect=[
                {
                    "ok": True,
                    "result": {
                        "phone_code_hash": "code-hash",
                        "session_string": "generated-pending",
                    },
                },
                {
                    "error": "2FA required",
                    "details": {
                        "status": "2fa_required",
                        "session_string": "generated-2fa-pending",
                    },
                },
                {
                    "ok": True,
                    "result": {
                        "session_string": "generated-authorized",
                        "user_id": 123,
                        "phone": "123456789",
                    },
                },
            ]
        )
        fields = {
            "source_reference": self.ref,
            "api_id": "123",
            "phone_number": "+123456789",
        }
        with patch.dict(_pending_telegram_auth, {}, clear=True):
            self.assertFalse(connect(system, "telegram_user", fields)[0])
            self.assertFalse(
                connect(system, "telegram_user", {**fields, "code": "12345"})[0]
            )
            new_reference = self.ref.rsplit("/", 1)[0] + "/2"
            self.assertTrue(
                connect(
                    system,
                    "telegram_user",
                    {**fields, "source_reference": new_reference, "code": "12345"},
                )[0]
            )
        stored = system.store_credential.call_args.args[2]
        self.assertEqual(stored["api_hash"], new_reference)
        self.assertEqual(stored["session_string"], "generated-authorized")
        self.assertEqual(
            ConfigStore.extras["source_telegram_auth"].await_args.args[:2],
            ("complete_password", "123"),
        )
        self.assertEqual(
            ConfigStore.extras["source_telegram_auth"].await_args.kwargs[
                "session_string"
            ],
            "generated-2fa-pending",
        )

    def test_host_qr_emits_only_generated_url_and_session_and_uses_saved_2fa(self):
        from telethon import errors
        from app.credentials.mtproto_helper import execute

        emitted, clients = [], []

        class Client:
            def __init__(self, session, *args, **kwargs):
                self.session = SimpleNamespace(save=lambda: "generated-session")
                self.connect, self.disconnect = AsyncMock(), AsyncMock()
                self.qr_login = AsyncMock(
                    return_value=SimpleNamespace(
                        url="tg://login?token=generated-qr",
                        wait=AsyncMock(
                            side_effect=errors.SessionPasswordNeededError(None)
                        ),
                    )
                )
                self.sign_in = AsyncMock()
                self.get_me = AsyncMock(
                    return_value=SimpleNamespace(
                        id=123,
                        first_name="Owner",
                        last_name="",
                        username="owner",
                        phone="123456789",
                    )
                )
                clients.append(self)

        class Execution:
            cancelled, status = Event(), None

            def start(self, status, content_type):
                self.status = status

            def emit(self, text):
                emitted.append(text)

        fields = Secret({"api_hash": "f" * 32, "password": "saved-2fa-password"})
        with patch("telethon.TelegramClient", Client):
            result = execute(
                route("auth_telegram_user", "qr_login"),
                fields,
                Mock(),
                {"body": {"api_id": "123"}},
                Execution(),
                Mock(),
            )
            self.assertEqual(result.content_type, "text/event-stream")
            records = [json.loads(part[6:]) for part in emitted]
            self.assertEqual(records[0]["qr_url"], "tg://login?token=generated-qr")
            self.assertEqual(records[1]["details"]["status"], "2fa_required")
            self.assertEqual(
                records[1]["details"]["session_string"], "generated-session"
            )
            self.assertNotIn("saved-2fa-password", "".join(emitted))
            result = execute(
                route("auth_telegram_user", "complete_password"),
                fields,
                Mock(),
                {"body": {"api_id": "123", "session_string": ""}},
                None,
                Mock(),
            )
            self.assertTrue(json.loads(result.body)["ok"])
            clients[-1].sign_in.assert_awaited_once_with(password="saved-2fa-password")


class AuthenticationMigrationTests(TestCase):
    def setUp(self):
        fixture = test_source_migration.SourceMigrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.vault, self.document = fixture.vault, fixture.document

    def test_migrate_app_secrets_preserves_all_generated_state_and_account_controls(
        self,
    ):
        for provider in (
            "twitter",
            "lark",
            "lark_drive",
            "lark_calendar",
            "telegram_user",
        ):
            with self.subTest(provider=provider):
                data = {
                    "access_token": "existing-access",
                    "access_token_secret": "existing-secret",
                    "refresh_token": "existing-refresh",
                    "session_string": "existing-session",
                    "session_id": "original-id",
                    "tenant_access_token": "existing-tenant",
                    "token_expires_at": 123,
                    "api_id": "123",
                    "app_id": "cli_123",
                }
                field = (
                    "api_secret"
                    if provider == "twitter"
                    else "api_hash"
                    if provider == "telegram_user"
                    else "app_secret"
                )
                data[field] = "c" * 32
                if provider == "twitter":
                    data["api_key"] = "synthetic-consumer-key"
                document = self.document(owner=data)
                before, commits = copy.deepcopy(document.reveal()), []
                result = migrate_integration_document(
                    self.vault, "synthetic-file", provider, document, commits.append
                )
                self.assertEqual(result.imported, 1)
                after = commits[0].reveal()["accounts"]["owner"]["credential"]
                for key in (
                    "access_token",
                    "access_token_secret",
                    "refresh_token",
                    "session_string",
                    "session_id",
                    "tenant_access_token",
                    "token_expires_at",
                ):
                    self.assertEqual(after[key], data[key])
                self.assertTrue(
                    is_reference(
                        after["source_reference" if provider == "twitter" else field]
                    )
                )
                self.assertEqual(document.reveal(), before)
                if provider == "twitter":
                    self.assertNotIn("api_key", after)
                    self.assertNotIn("api_secret", after)
                repeated = migrate_integration_document(
                    self.vault,
                    "synthetic-file",
                    provider,
                    commits[0],
                    lambda value: None,
                )
                self.assertEqual(repeated.imported, 0)

    def test_telegram_env_migration_preserves_api_id_tokens_and_sessions_exactly(self):
        original = (
            '\ufeffTELEGRAM_API_ID=123\r\nTELEGRAM_API_HASH="'
            + "d" * 32
            + '" # app\r\nSESSION_ID=existing\r\nACCESS_TOKEN=existing-access\r\n'
        )
        commits = []
        result = migrate_environment_document(
            self.vault, "synthetic-env", Secret(original), commits.append
        )
        self.assertEqual(result.imported, 1)
        text = commits[0].reveal()
        self.assertIn("\ufeffTELEGRAM_API_ID=123\r\n", text)
        self.assertIn(
            " # app\r\nSESSION_ID=existing\r\nACCESS_TOKEN=existing-access\r\n", text
        )
        self.assertNotIn("d" * 32, text)
        self.assertIn("craftbot-vault://", text)
