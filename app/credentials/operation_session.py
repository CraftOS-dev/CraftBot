"""Short-lived, exact-operation polling sessions; every grant needs native consent."""

import json
import time
from threading import Lock
from .client import CredentialHostUnavailable, request
from .invocation import CredentialResponse
from .references import parse


class OperationSession:
    def __init__(self, reference, helper, operation, subject):
        ref = parse(reference)
        self.lock, self.closed = Lock(), False
        arguments = dict(
            helper=helper,
            operation=operation,
            credential_id=str(ref.credential_id),
            credential_version=ref.version,
            repeat=True,
        )
        source = (
            "import credential_client, time\ndata = "
            + repr(arguments)
            + "\n"
            + """
grant = None
try:
    while True:
        while not credential_client.request('payload_info')['ready']:
            time.sleep(0.05)
        if grant is None:
            approval = credential_client.request('request_use', **data)
            grant = approval['grant_id']
        else:
            approval = credential_client.request('authorize_grant', grant_id=grant)
        credential_client.request('start_use_staged', capability=approval['capability'])
        while not credential_client.request('operation_status')['done']:
            time.sleep(0.05)
        while credential_client.request('operation_status')['active']:
            time.sleep(0.05)
except Exception:
    credential_client.complete({'error': 'credential_operation_failed'})
"""
        )
        self.run_id = request(
            "launch",
            profile_id=str(ref.profile_id),
            kind="agent_session",
            subject=subject,
            deployment=None,
            files={"poll.py": source},
            entry="poll.py",
        )["run_id"]
        self.expires = time.monotonic() + 850

    def invoke(self, body, *, cancelled):
        with self.lock:
            if self.closed or time.monotonic() >= self.expires:
                raise CredentialHostUnavailable("credential_grant_expired")
            serialized = json.dumps(
                body, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            )
            if len(serialized) > 32_000_000:
                raise CredentialHostUnavailable("credential_use_limit")
            try:
                for offset in range(0, len(serialized), 8000):
                    chunk = serialized[offset : offset + 8000]
                    request(
                        "stage_payload",
                        run_id=self.run_id,
                        offset=offset,
                        data=chunk,
                        done=offset + len(chunk) == len(serialized),
                    )
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline:
                    if cancelled.is_set():
                        raise CredentialHostUnavailable("credential_use_interrupted")
                    result = request("result", run_id=self.run_id)
                    if "response" in result:
                        response = CredentialResponse(
                            self.run_id,
                            result["response"],
                            cancelled,
                            stop_on_close=False,
                        )
                        text = "".join(response)
                        request("reset_operation", run_id=self.run_id)
                        return dict(
                            status=response.status,
                            content_type=response.content_type,
                            body=text,
                        )
                    if "exited" in result or "result" in result:
                        raise CredentialHostUnavailable("credential_operation_failed")
                    time.sleep(0.05)
                raise CredentialHostUnavailable("credential_operation_timeout")
            except BaseException:
                self.close()
                raise

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                request("stop", run_id=self.run_id)
            except CredentialHostUnavailable:
                pass
