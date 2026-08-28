"""LinkedIn operations — schemas for linkedin_actions.py.

Complete port of app/data/action/integrations/linkedin/linkedin_actions.py
— all 31 actions, same names/descriptions/schemas/arg mapping. No
operation declares an ``account`` input (conformance-enforced; the host
injects it).

Porting notes:
- ``irreversible=True`` (send_linkedin_message,
  send_linkedin_connection_request) → ``destructive=True``. Per the same
  rule, every outward-facing social send (create/reshare post, like,
  comment, follow, respond to invitation) and every permanent delete
  (post, comment) is ``destructive=True`` + ``parallelizable=False``.
  Reversible mutations (unlike, unfollow) stay non-destructive but are
  serialized (``parallelizable=False``).
- The author/actor URN (``urn:li:person:<id>``) is derived from the
  *bound account's* credential — ``_person_urn`` verbatim, now per
  account via the injected credential instead of the shared linkedin.json.
- Envelope handling matches ``run_client_sync``/``with_client``
  defaults exactly: the client's ``{"ok": ..., "result": ...}`` transport
  envelope is collapsed by ``shape_result`` with no ``unwrap_envelope``
  opt-in, so restricted-API responses carrying a ``"note"`` field surface
  the same way they always did.
- The lean ugcPosts shaping of get_my_linkedin_posts /
  get_linkedin_organization_posts is reproduced verbatim (the port has no
  double transport envelope, so the inner-envelope collapse
  step is unnecessary here).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...contracts import Operation
from .._shared import client_op, shape_result

_STATUS = {"status": {"type": "string", "example": "success"}}


def _person_urn(client: Any) -> str:
    """LinkedIn URN of the bound account — author/actor for posts, likes,
    comments, messages, follows. Per-account."""
    cred = client._load()
    return (
        f"urn:li:person:{cred.linkedin_id}"
        if cred.linkedin_id
        else f"urn:li:person:{cred.user_id}"
    )


def _urn_op(
    name: str,
    method: str,
    *,
    description: str,
    input_schema: Dict[str, Any],
    args: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    destructive: bool = False,
    parallelizable: bool = True,
    output_schema: Optional[Dict[str, Any]] = None,
    tags: Tuple[str, ...] = ("linkedin",),
) -> Operation:
    """Like ``client_op`` but for methods needing the bound account's
    person URN: ``args(person_urn, input_data)`` builds the kwargs."""

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            kwargs = args(_person_urn(client), input_data)
            raw = await asyncio.to_thread(getattr(client, method), **kwargs)
            return shape_result(raw)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return Operation(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema or dict(_STATUS),
        fn=fn,
        destructive=destructive,
        parallelizable=parallelizable,
        tags=tags,
    )


# ────────────────────────────────────────────────────────────────────────
# Post-processing (lean ugcPosts shaping)
# ────────────────────────────────────────────────────────────────────────


def _with_post(
    base: Operation,
    post: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Operation:
    """Wrap an operation's fn with a (result, input_data) post-processor."""
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return post(await inner(client, input_data), input_data)

    return replace(base, fn=fn)


def _lean_ugc_posts(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Lean shaping: {id, text, created, lifecycleState, media} per
    post unless include_metadata=true asked for the full raw ugcPosts."""
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict) or "error" in body:
        return res

    posts = []
    for el in body.get("elements", []) or []:
        if not isinstance(el, dict):
            continue
        share = (el.get("specificContent") or {}).get(
            "com.linkedin.ugc.ShareContent"
        ) or {}
        p = {
            "id": el.get("id"),
            "text": (share.get("shareCommentary") or {}).get("text"),
            "created": (el.get("created") or {}).get("time"),
            "lifecycleState": el.get("lifecycleState"),
        }
        media = share.get("media")
        if media:
            p["media"] = [
                {k: v for k, v in m.items() if k in ("media", "originalUrl", "status")}
                for m in media
                if isinstance(m, dict)
            ]
        posts.append(p)
    lean: Dict[str, Any] = {"posts": posts}
    if isinstance(body.get("paging"), dict):
        pg = body["paging"]
        lean["paging"] = {
            "start": pg.get("start"),
            "count": pg.get("count"),
            "total": pg.get("total"),
        }
    return {**res, "result": lean}


# ────────────────────────────────────────────────────────────────────────
# Operations
# ────────────────────────────────────────────────────────────────────────


def build_operations() -> List[Operation]:
    return [
        # ── Profile ──────────────────────────────────────────────────────
        client_op(
            "get_linkedin_profile",
            "get_user_profile",
            description="Get the authenticated user's LinkedIn profile.",
            tags=("linkedin",),
            input_schema={},
        ),
        # ── Posts (create / delete / get / list / org posts / reshare) ───
        _urn_op(
            "create_linkedin_post",
            "create_text_post",
            description="Create a text post on LinkedIn.",
            destructive=True,  # outward-facing send — visible to the network
            parallelizable=False,
            input_schema={
                "text": {
                    "type": "string",
                    "description": "Post text (max 3000 chars).",
                    "example": "Excited to share...",
                },
                "visibility": {
                    "type": "string",
                    "description": "Visibility: PUBLIC, CONNECTIONS, or LOGGED_IN.",
                    "example": "PUBLIC",
                },
            },
            args=lambda urn, d: {
                "author_urn": urn,
                "text": d["text"],
                "visibility": d.get("visibility", "PUBLIC"),
            },
        ),
        client_op(
            "delete_linkedin_post",
            "delete_post",
            description="Delete a LinkedIn post.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("linkedin",),
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
        ),
        client_op(
            "get_linkedin_post",
            "get_post",
            description="Get a post.",
            tags=("linkedin",),
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
        ),
        _with_post(
            _urn_op(
                "get_my_linkedin_posts",
                "get_posts_by_author",
                description=(
                    "Get my posts. Lean posts ({id, text, created, "
                    "lifecycleState, media}) by default; include_metadata=true "
                    "returns the full raw ugcPosts."
                ),
                input_schema={
                    "count": {
                        "type": "integer",
                        "description": "Count.",
                        "example": 50,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean posts. True: full raw ugcPosts.",
                        "example": False,
                    },
                },
                args=lambda urn, d: {
                    "author_urn": urn,
                    "count": d.get("count", 50),
                },
            ),
            _lean_ugc_posts,
        ),
        _with_post(
            client_op(
                "get_linkedin_organization_posts",
                "get_posts_by_author",
                description=(
                    "Get organization posts. Lean posts ({id, text, created, "
                    "lifecycleState, media}) by default; include_metadata=true "
                    "returns the full raw ugcPosts."
                ),
                tags=("linkedin",),
                input_schema={
                    "organization_urn": {
                        "type": "string",
                        "description": "Org URN.",
                        "example": "urn:li:organization:123",
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean posts. True: full raw ugcPosts.",
                        "example": False,
                    },
                },
                arg_map=lambda d: {"author_urn": d["organization_urn"]},
            ),
            _lean_ugc_posts,
        ),
        _urn_op(
            "reshare_linkedin_post",
            "reshare_post",
            description="Reshare a post.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            input_schema={
                "original_post_urn": {
                    "type": "string",
                    "description": "Original Post URN.",
                    "example": "urn:li:share:123",
                },
                "commentary": {
                    "type": "string",
                    "description": "Commentary.",
                    "example": "Interesting!",
                },
            },
            args=lambda urn, d: {
                "author_urn": urn,
                "original_post_urn": d["original_post_urn"],
                "commentary": d.get("commentary", ""),
            },
        ),
        # ── Reactions / Comments ─────────────────────────────────────────
        _urn_op(
            "like_linkedin_post",
            "like_post",
            description="Like a post.",
            destructive=True,  # outward-facing send — visible to the author
            parallelizable=False,
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
            args=lambda urn, d: {"actor_urn": urn, "post_urn": d["post_urn"]},
        ),
        _urn_op(
            "unlike_linkedin_post",
            "unlike_post",
            description="Unlike a post.",
            parallelizable=False,  # reversible mutation — serialized, not flagged
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
            args=lambda urn, d: {"actor_urn": urn, "post_urn": d["post_urn"]},
        ),
        client_op(
            "get_linkedin_post_likes",
            "get_post_reactions",
            description="Get post likes.",
            tags=("linkedin",),
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
        ),
        _urn_op(
            "comment_on_linkedin_post",
            "comment_on_post",
            description="Comment on a post.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                },
                "text": {
                    "type": "string",
                    "description": "Comment text.",
                    "example": "Great post!",
                },
            },
            args=lambda urn, d: {
                "actor_urn": urn,
                "post_urn": d["post_urn"],
                "text": d["text"],
            },
        ),
        client_op(
            "get_linkedin_post_comments",
            "get_post_comments",
            description="Get post comments.",
            tags=("linkedin",),
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
        ),
        _urn_op(
            "delete_linkedin_comment",
            "delete_comment",
            description="Delete a comment.",
            destructive=True,  # permanent delete
            parallelizable=False,
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                },
                "comment_urn": {
                    "type": "string",
                    "description": "Comment URN.",
                    "example": "urn:li:comment:123",
                },
            },
            args=lambda urn, d: {
                "actor_urn": urn,
                "post_urn": d["post_urn"],
                "comment_urn": d["comment_urn"],
            },
        ),
        # ── Connections / Invitations / Messages ─────────────────────────
        client_op(
            "get_linkedin_connections",
            "get_connections",
            description="Get the authenticated user's LinkedIn connections.",
            tags=("linkedin",),
            input_schema={
                "count": {
                    "type": "integer",
                    "description": "Number of connections to return.",
                    "example": 50,
                },
            },
            arg_map=lambda d: {"count": d.get("count", 50)},
        ),
        _urn_op(
            "send_linkedin_message",
            "send_message_to_recipients",
            description="Send a message to LinkedIn users.",
            destructive=True,  # outward-facing DM
            parallelizable=False,
            input_schema={
                "recipient_urns": {
                    "type": "array",
                    "description": "List of recipient URNs (urn:li:person:xxx).",
                    "example": [],
                },
                "subject": {
                    "type": "string",
                    "description": "Message subject.",
                    "example": "Hello",
                },
                "body": {
                    "type": "string",
                    "description": "Message body.",
                    "example": "Hi, I wanted to connect...",
                },
            },
            args=lambda urn, d: {
                "sender_urn": urn,
                "recipient_urns": d["recipient_urns"],
                "subject": d["subject"],
                "body": d["body"],
            },
        ),
        client_op(
            "send_linkedin_connection_request",
            "send_connection_request",
            description="Send connection request.",
            destructive=True,  # outward-facing invite
            parallelizable=False,
            tags=("linkedin",),
            input_schema={
                "invitee_profile_urn": {
                    "type": "string",
                    "description": "Profile URN.",
                    "example": "urn:li:person:123",
                },
                "message": {
                    "type": "string",
                    "description": "Message.",
                    "example": "Hi",
                },
            },
            arg_map=lambda d: {
                "invitee_profile_urn": d["invitee_profile_urn"],
                "message": d.get("message"),
            },
        ),
        client_op(
            "get_linkedin_sent_invitations",
            "get_sent_invitations",
            description="Get sent invitations.",
            tags=("linkedin",),
            input_schema={
                "count": {"type": "integer", "description": "Count.", "example": 50}
            },
            arg_map=lambda d: {"count": d.get("count", 50)},
        ),
        client_op(
            "get_linkedin_received_invitations",
            "get_received_invitations",
            description="Get received invitations.",
            tags=("linkedin",),
            input_schema={
                "count": {"type": "integer", "description": "Count.", "example": 50}
            },
            arg_map=lambda d: {"count": d.get("count", 50)},
        ),
        client_op(
            "respond_to_linkedin_invitation",
            "respond_to_invitation",
            description="Respond to invitation.",
            destructive=True,  # accept/ignore cannot be taken back
            parallelizable=False,
            tags=("linkedin",),
            input_schema={
                "invitation_urn": {
                    "type": "string",
                    "description": "Invitation URN.",
                    "example": "urn:li:invitation:123",
                },
                "action": {
                    "type": "string",
                    "description": "accept/ignore.",
                    "example": "accept",
                },
            },
            arg_map=lambda d: {
                "invitation_urn": d["invitation_urn"],
                "action": d["action"],
            },
        ),
        client_op(
            "get_linkedin_conversations",
            "get_conversations",
            description="Get conversations.",
            tags=("linkedin",),
            input_schema={
                "count": {"type": "integer", "description": "Count.", "example": 20}
            },
            arg_map=lambda d: {"count": d.get("count", 20)},
        ),
        # ── Search / Lookups ─────────────────────────────────────────────
        client_op(
            "search_linkedin_jobs",
            "search_jobs",
            description="Search for job postings on LinkedIn.",
            tags=("linkedin",),
            input_schema={
                "keywords": {
                    "type": "string",
                    "description": "Job search keywords.",
                    "example": "software engineer",
                },
                "location": {
                    "type": "string",
                    "description": "Optional location filter.",
                    "example": "",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results.",
                    "example": 25,
                },
            },
            arg_map=lambda d: {
                "keywords": d["keywords"],
                "location": d.get("location"),
                "count": d.get("count", 25),
            },
        ),
        client_op(
            "get_linkedin_job_details",
            "get_job_details",
            description="Get job details.",
            tags=("linkedin",),
            input_schema={
                "job_id": {"type": "string", "description": "Job ID.", "example": "123"}
            },
        ),
        client_op(
            "search_linkedin_companies",
            "search_companies",
            description="Search companies.",
            tags=("linkedin",),
            input_schema={
                "keywords": {
                    "type": "string",
                    "description": "Keywords.",
                    "example": "tech",
                }
            },
        ),
        client_op(
            "lookup_linkedin_company",
            "get_company_by_vanity_name",
            description="Lookup company by vanity name.",
            tags=("linkedin",),
            input_schema={
                "vanity_name": {
                    "type": "string",
                    "description": "Vanity name.",
                    "example": "microsoft",
                }
            },
        ),
        client_op(
            "get_linkedin_person",
            "get_person",
            description="Get person profile by ID.",
            tags=("linkedin",),
            input_schema={
                "person_id": {
                    "type": "string",
                    "description": "Person ID.",
                    "example": "123",
                }
            },
        ),
        # ── Organizations / Analytics / Follow ───────────────────────────
        client_op(
            "get_linkedin_organizations",
            "get_my_organizations",
            description="Get user's organizations.",
            tags=("linkedin",),
            input_schema={},
        ),
        client_op(
            "get_linkedin_organization_info",
            "get_organization",
            description="Get organization info.",
            tags=("linkedin",),
            input_schema={
                "organization_id": {
                    "type": "string",
                    "description": "Org ID.",
                    "example": "123",
                }
            },
        ),
        client_op(
            "get_linkedin_organization_analytics",
            "get_organization_analytics",
            description="Get organization analytics.",
            tags=("linkedin",),
            input_schema={
                "organization_urn": {
                    "type": "string",
                    "description": "Org URN.",
                    "example": "urn:li:organization:123",
                }
            },
        ),
        client_op(
            "get_linkedin_post_analytics",
            "get_post_analytics",
            description="Get post analytics.",
            tags=("linkedin",),
            input_schema={
                "post_urn": {
                    "type": "string",
                    "description": "Post URN.",
                    "example": "urn:li:share:123",
                }
            },
            arg_map=lambda d: {"share_urns": [d["post_urn"]]},
        ),
        _urn_op(
            "follow_linkedin_organization",
            "follow_organization",
            description="Follow organization.",
            destructive=True,  # outward-facing send — visible to the org
            parallelizable=False,
            input_schema={
                "organization_urn": {
                    "type": "string",
                    "description": "Org URN.",
                    "example": "urn:li:organization:123",
                }
            },
            args=lambda urn, d: {
                "follower_urn": urn,
                "organization_urn": d["organization_urn"],
            },
        ),
        _urn_op(
            "unfollow_linkedin_organization",
            "unfollow_organization",
            description="Unfollow organization.",
            parallelizable=False,  # reversible mutation — serialized, not flagged
            input_schema={
                "organization_urn": {
                    "type": "string",
                    "description": "Org URN.",
                    "example": "urn:li:organization:123",
                }
            },
            args=lambda urn, d: {
                "follower_urn": urn,
                "organization_urn": d["organization_urn"],
            },
        ),
    ]
