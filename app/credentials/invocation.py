"""Host-blind controllers execute fixed operations through an isolated worker.

Only source references, request data and sanitized responses cross this module.
The native host confirms launch, then independently confirms the one-use grant.
The public SDK never obtains a raw credential or an authenticated HTTP client.
"""

import json
import hashlib
import time

from .client import CredentialHostUnavailable, request
from .references import parse


def open_response(
    reference: str,
    helper: str,
    operation: str,
    body=None,
    *,
    subject="credential operation",
    cancelled=None,
):
    ref = parse(reference)
    serialized = json.dumps(
        body, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    if len(serialized) > 32_000_000:
        raise CredentialHostUnavailable("credential_use_limit")
    data = {
        "helper": helper,
        "operation": operation,
        "credential_id": str(ref.credential_id),
        "credential_version": ref.version,
    }
    source = (
        "import credential_client, time\ndata = "
        + repr(data)
        + "\nexpected = "
        + repr(hashlib.sha256(serialized.encode("ascii")).hexdigest())
        + """
try:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        info = credential_client.request('payload_info')
        if info['ready']:
            break
        time.sleep(0.1)
    if not info['ready'] or info['sha256'] != expected:
        raise RuntimeError()
    approval = credential_client.request('request_use', **data)
    credential_client.request('start_use_staged', capability=approval['capability'])
    while not credential_client.request('operation_status')['done']:
        time.sleep(0.1)
    credential_client.complete({'outcome': 'completed'})
except Exception:
    credential_client.complete({'error': 'credential_operation_failed'})
"""
    )
    if len(json.dumps({"call.py": source}).encode("utf-8")) > 47000:
        raise CredentialHostUnavailable("credential_use_limit")
    launch = request(
        "launch",
        profile_id=str(ref.profile_id),
        kind="agent_session",
        subject=subject,
        deployment=None,
        files={"call.py": source},
        entry="call.py",
    )
    try:
        for offset in range(0, len(serialized), 8000):
            chunk = serialized[offset : offset + 8000]
            request(
                "stage_payload",
                run_id=launch["run_id"],
                offset=offset,
                data=chunk,
                done=offset + len(chunk) == len(serialized),
            )
        deadline = time.monotonic() + 900  # Includes interactive owner prompts.
        while time.monotonic() < deadline:
            if cancelled is not None and cancelled.is_set():
                raise CredentialHostUnavailable("credential_use_interrupted")
            result = request("result", run_id=launch["run_id"])
            if "response" in result:
                response = result["response"]
                length = response["length"]
                if type(length) is not int or not 0 <= length <= 96_000_000:
                    raise CredentialHostUnavailable("credential_response_invalid")
                return CredentialResponse(launch["run_id"], response, cancelled)
            if (
                "result" in result
                and type(result["result"]) is dict
                and result["result"].get("outcome")
                in ("accepted", "rejected", "unavailable")
            ):
                outcome = result["result"]["outcome"]
                request("stop", run_id=launch["run_id"])
                return StaticResponse(
                    {"accepted": 200, "rejected": 401, "unavailable": 503}[outcome],
                    json.dumps({"outcome": outcome}),
                )
            if "result" in result or "exited" in result:
                raise CredentialHostUnavailable("credential_operation_failed")
            time.sleep(0.15)
        raise CredentialHostUnavailable("credential_operation_timeout")
    except BaseException:
        try:
            request("stop", run_id=launch["run_id"])
        except CredentialHostUnavailable:
            pass
        raise


class CredentialResponse:
    def __init__(self, run_id, metadata, cancelled=None, *, stop_on_close=True):
        self.run_id, self.status, self.content_type = (
            run_id,
            metadata["status"],
            metadata["content_type"],
        )
        self.initial, self.cancelled, self.closed = metadata, cancelled, False
        self.stop_on_close = stop_on_close

    def __iter__(self):
        offset, deadline = 0, time.monotonic() + 900
        try:
            while time.monotonic() < deadline:
                if self.cancelled is not None and self.cancelled.is_set():
                    raise CredentialHostUnavailable("credential_use_interrupted")
                result = request("response", run_id=self.run_id, offset=offset)
                if result.get("error"):
                    raise CredentialHostUnavailable("credential_operation_failed")
                chunk = result["chunk"]
                if not isinstance(chunk, str) or len(chunk) > 8000:
                    raise CredentialHostUnavailable("credential_response_invalid")
                if chunk:
                    offset += len(chunk)
                    if offset > 96_000_000:
                        raise CredentialHostUnavailable("credential_use_limit")
                    yield chunk
                done = result.get("done", self.initial.get("done", True))
                length = result.get("length", self.initial["length"])
                if done and offset >= length:
                    return
                if not chunk:
                    time.sleep(0.025)
            raise CredentialHostUnavailable("credential_operation_timeout")
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            if self.stop_on_close:
                try:
                    request("stop", run_id=self.run_id)
                except CredentialHostUnavailable:
                    pass


class StaticResponse:
    content_type = "application/json"

    def __init__(self, status, body):
        self.status, self.body = status, body

    def __iter__(self):
        yield self.body

    def close(self):
        pass


def invoke(
    reference,
    helper,
    operation,
    body=None,
    *,
    subject="credential operation",
    cancelled=None,
):
    response = open_response(
        reference, helper, operation, body, subject=subject, cancelled=cancelled
    )
    try:
        return {
            "status": response.status,
            "content_type": response.content_type,
            "body": "".join(response),
        }
    finally:
        response.close()


async def invoke_async(*args, **kwargs):
    import asyncio
    from threading import Event

    cancelled = Event()
    task = asyncio.create_task(
        asyncio.to_thread(invoke, *args, **kwargs, cancelled=cancelled)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        # The host closes an active socket when stop reaches the control pipe.
        # Dispatched provider effects cannot be retracted.
        task.add_done_callback(
            lambda future: future.exception() if not future.cancelled() else None
        )
        raise
