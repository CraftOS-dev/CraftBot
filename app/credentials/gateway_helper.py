"""Reviewed Discord Gateway identify + heartbeat + event receiver.

No caller-selected WS URL, identify fields, messages, session/resume or signer.
The bot source is used only on the pinned, verified Discord TLS connection.
"""

import json
import logging
import socket
import ssl
import time
from threading import Event, Thread, Timer

from .helpers import JsonResult, _address, _abort_socket
from .secrets import Secret
from .streaming import StreamFilter
from .use_errors import CredentialUseError, UseCode


def execute(spec, fields, guard, payload, execution, after_send):
    if payload != {"body": None} or execution is None:
        raise CredentialUseError(UseCode.DENIED)
    from websockets.sync.client import connect

    family, socktype, protocol, address = _address("gateway.discord.gg", 443)
    guard()
    logger = logging.Logger("credential_gateway_private")
    logger.disabled, logger.propagate = True, False
    deadline = time.monotonic() + 600
    finished, timer = Event(), None
    try:
        with socket.socket(family, socktype, protocol) as transport:
            transport.settimeout(10)
            transport.connect(address)
            with connect(
                "wss://gateway.discord.gg/?v=10&encoding=json",
                sock=transport,
                ssl=ssl.create_default_context(),
                proxy=None,
                compression=None,
                open_timeout=10,
                close_timeout=1,
                max_size=1_000_000,
                max_queue=4,
                ping_interval=None,
                logger=logger,
            ) as websocket:
                timer = Timer(600, _abort_socket, args=(websocket.socket,))
                timer.daemon = True
                timer.start()

                def watch():
                    while not finished.wait(0.05):
                        if execution.cancelled.is_set():
                            _abort_socket(websocket.socket)
                            return

                Thread(target=watch, daemon=True).start()
                hello = json.loads(websocket.recv(timeout=10))
                interval = hello.get("d", {}).get("heartbeat_interval")
                if (
                    hello.get("op") != 10
                    or type(interval) not in (int, float)
                    or not 1000 <= interval <= 120000
                ):
                    raise CredentialUseError(UseCode.HELPER)
                guard()
                token = Secret(fields.reveal()["api_key"])
                if not token.reveal().isascii() or any(
                    ord(c) < 33 or ord(c) > 126 for c in token.reveal()
                ):
                    raise CredentialUseError(UseCode.DENIED)
                identify = Secret(
                    {
                        "op": 2,
                        "d": {
                            "token": token.reveal(),
                            "intents": 37376,
                            "properties": {
                                "os": "windows",
                                "browser": "craftosbot",
                                "device": "craftosbot",
                            },
                        },
                    }
                )
                websocket.send(json.dumps(identify.reveal()))
                if after_send is not None:
                    after_send()
                execution.start(200, "text/event-stream")
                filtering = StreamFilter(
                    Secret({"token": token.reveal()}), execution.emit
                )
                heartbeat = time.monotonic()
                last_ack, sequence = heartbeat, None
                while time.monotonic() < deadline:
                    if execution.cancelled.is_set():
                        raise CredentialUseError(UseCode.INTERRUPTED)
                    now = time.monotonic()
                    if now >= heartbeat:
                        if now - last_ack > 2 * interval / 1000:
                            raise CredentialUseError(UseCode.HELPER)
                        websocket.send(json.dumps({"op": 1, "d": sequence}))
                        heartbeat = now + interval / 1000
                    try:
                        message = websocket.recv(
                            timeout=min(1, max(0.01, heartbeat - now))
                        )
                    except TimeoutError:
                        continue
                    if not isinstance(message, str):
                        raise CredentialUseError(UseCode.HELPER)
                    data = json.loads(message)
                    if type(data) is not dict or type(data.get("op")) is not int:
                        raise CredentialUseError(UseCode.HELPER)
                    if data.get("s") is not None:
                        if type(data["s"]) is not int:
                            raise CredentialUseError(UseCode.HELPER)
                        sequence = data["s"]
                    if data["op"] == 11:
                        last_ack = time.monotonic()
                    elif data["op"] == 1:
                        heartbeat = 0
                    elif data["op"] in (7, 9):
                        break  # New bounded worker/consent; never auto-resume.
                    elif data["op"] == 0 and data.get("t") in (
                        "READY",
                        "MESSAGE_CREATE",
                    ):
                        filtering.feed("data: " + json.dumps(data))
                filtering.flush()
                return JsonResult(200, "", "text/event-stream")
    finally:
        finished.set()
        if timer is not None:
            timer.cancel()
