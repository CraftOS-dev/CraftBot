"""Launch credential-enabled Python code through the protected host only."""

import asyncio
import json
import time

from .client import CredentialHostUnavailable, request


async def execute_action(
    code: str, input_data: dict, *, profile_id: str, subject: str, timeout: int
):
    # This wrapper is untrusted consumer code. All authority still comes from
    # the native launch, kernel peer/job checks and explicit native owner consent.
    data = json.dumps(input_data)
    source = (
        "code = "
        + repr(code)
        + "\ndata = "
        + repr(data)
        + "\n"
        + """import asyncio, inspect, json
import credential_client
namespace = {'__name__': '__credential_action__'}
try:
    exec(code, namespace, namespace)
    function = next(value for value in namespace.values() if inspect.isfunction(value) and value.__globals__ is namespace)
    result = function(json.loads(data))
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    credential_client.complete(result)
except BaseException:
    credential_client.complete({'status': 'error', 'message': 'Isolated action failed'})
"""
    )
    launch = await asyncio.to_thread(
        request,
        "launch",
        profile_id=profile_id,
        kind="agent_session",
        subject=subject,
        deployment=None,
        files={"action.py": source},
        entry="action.py",
    )
    deadline = time.monotonic() + min(timeout, 900)
    try:
        while time.monotonic() < deadline:
            result = await asyncio.to_thread(
                request, "program_result", run_id=launch["run_id"]
            )
            if "result" in result:
                return result["result"]
            if "exited" in result:
                return {
                    "status": "error",
                    "message": "Isolated credential action exited without a result",
                }
            await asyncio.sleep(0.2)
        return {"status": "error", "message": "Isolated credential action timed out"}
    finally:
        try:
            await asyncio.to_thread(request, "stop", run_id=launch["run_id"])
        except CredentialHostUnavailable:
            pass  # Host restart/lock already killed the job; no legacy fallback.
