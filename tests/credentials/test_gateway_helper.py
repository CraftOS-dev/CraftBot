"""Exercise fixed Discord identify/heartbeat/events against synthetic sockets."""

import json
from unittest.mock import Mock, MagicMock, patch
import unittest

from app.credentials.catalog import integration_helpers, specification
from app.credentials.execution import OperationJob
from app.credentials.helpers import _execute_json
from app.credentials.secrets import Secret
from app.credentials.use_errors import CredentialUseError
from test_broker import wire


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.spec = specification(
            next(r for r in integration_helpers() if r["operation"] == "gateway_events")
        )
        self.fields = Secret({"api_key": "SyntheticDiscordBot-Secret-999"})

    def test_identify_stays_private_while_sanitized_events_and_generated_session_return(
        self,
    ):
        websocket = MagicMock()
        websocket.__enter__.return_value = websocket
        websocket.recv.side_effect = [
            json.dumps({"op": 10, "d": {"heartbeat_interval": 40000}}),
            json.dumps(
                {
                    "op": 0,
                    "t": "READY",
                    "s": 1,
                    "d": {"session_id": "generated-session", "user": {"id": "bot-id"}},
                }
            ),
            json.dumps(
                {"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": {"content": "hello"}}
            ),
            json.dumps({"op": 7}),
        ]
        output = OperationJob(lambda job: None)
        dispatched, guard = Mock(), Mock()
        with (
            wire(),
            patch("websockets.sync.client.connect", return_value=websocket) as connect,
        ):
            result = _execute_json(
                self.spec,
                self.fields,
                guard,
                {"body": None},
                execution=output,
                after_send=dispatched,
            )
        self.assertEqual(result.content_type, "text/event-stream")
        self.assertIn("generated-session", output.body)
        self.assertIn("hello", output.body)
        self.assertNotIn(self.fields.reveal()["api_key"], output.body)
        identify = json.loads(websocket.send.call_args_list[0].args[0])
        self.assertEqual(identify["d"]["token"], self.fields.reveal()["api_key"])
        self.assertEqual(identify["d"]["intents"], 37376)
        self.assertIsNone(connect.call_args.kwargs["proxy"])
        self.assertIsNone(connect.call_args.kwargs["compression"])
        self.assertIn("sock", connect.call_args.kwargs)
        self.assertGreaterEqual(guard.call_count, 2)
        dispatched.assert_called_once()

    def test_handshake_failure_never_identifies_and_payload_cannot_supply_protocol_frames(
        self,
    ):
        with (
            wire(),
            patch(
                "websockets.sync.client.connect",
                side_effect=RuntimeError("private-TLS-error"),
            ),
        ):
            with self.assertRaises(CredentialUseError):
                _execute_json(
                    self.spec,
                    self.fields,
                    Mock(),
                    {"body": None},
                    execution=OperationJob(lambda j: None),
                )
        with patch("websockets.sync.client.connect") as connect:
            with self.assertRaises(CredentialUseError):
                _execute_json(
                    self.spec,
                    self.fields,
                    Mock(),
                    {"body": {"token": "forged", "url": "wss://attacker.test"}},
                    execution=OperationJob(lambda j: None),
                )
            connect.assert_not_called()
