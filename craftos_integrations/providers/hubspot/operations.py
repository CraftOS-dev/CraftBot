"""HubSpot operations — ported from the legacy hubspot_actions.py schemas.

Complete port of app/data/action/integrations/hubspot/hubspot_actions.py —
all 90 actions, same names/descriptions/schemas/arg mapping. No operation
declares an ``account`` input (conformance-enforced; the host injects it).

Porting notes:
- Legacy ``irreversible=True`` (send_hubspot_single_send,
  send_hubspot_conversation_message) → ``destructive=True``; delete/remove
  operations are also flagged destructive per the conformance rule.
  Legacy ``parallelizable=False`` (every mutation) carries over 1:1.
- The HubSpot client returns the package's ``{ok: True, result: ...}`` /
  ``{error, details}`` envelope from ``helpers.http.arequest`` — exactly
  what ``client_op``'s default ``shape_result`` collapses, so envelope
  handling matches legacy ``run_client`` behavior with no options.
- Post-processing is reproduced verbatim via fn-wrapping (same pattern as
  slack/gmail): ``_pick`` = legacy ``pick_result``; ``_lean_listing`` =
  the per-row archived/createdAt/updatedAt strip + paging.next.link drop
  applied to every list/search action; ``_batch_ids`` and
  ``_created_list_id`` are the two bespoke reducers.
- Comma-separated ``properties``/``associations`` inputs are split into
  lists exactly as the legacy actions did (``_csv``).

The legacy file's "intentionally NOT exposed" list carries over
unchanged: Workflows/Automation authoring, CMS Hub, CTAs, Settings
(users/teams), Quotes/Line Items/Products, Payments, Custom Object
schema authoring, Analytics ingestion, Email Subscription preferences,
legacy v1 single-send, Calling/Video extensions were never actions and
stay out.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from ...contracts import Operation
from .._shared import client_op

_STATUS = {"status": {"type": "string", "example": "success"}}


# ────────────────────────────────────────────────────────────────────────
# Schema-fragment builders (fresh dicts; descriptions/examples verbatim)
# ────────────────────────────────────────────────────────────────────────


def _s(description: str, example: str = "") -> Dict[str, Any]:
    return {"type": "string", "description": description, "example": example}


def _i(description: str, example: int) -> Dict[str, Any]:
    return {"type": "integer", "description": description, "example": example}


def _b(description: str, example: bool = False) -> Dict[str, Any]:
    return {"type": "boolean", "description": description, "example": example}


def _arr(description: str, example: List[Any]) -> Dict[str, Any]:
    return {"type": "array", "description": description, "example": example}


def _obj(description: str, example: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "description": description, "example": example}


def _limit(example: int = 30, description: str = "Max results.") -> Dict[str, Any]:
    return _i(description, example)


def _after() -> Dict[str, Any]:
    return _s("Pagination cursor.", "")


def _only(description: str) -> Dict[str, Any]:
    return {**_STATUS, "result": {"type": "object", "description": description}}


# ────────────────────────────────────────────────────────────────────────
# Post-processing helpers (legacy shaping, verbatim)
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


def _pick(keys: List[str]):
    """Legacy ``pick_result``: reduce a successful result to named keys."""

    def post(res: Dict[str, Any], _input: Dict[str, Any]) -> Dict[str, Any]:
        if res.get("status") == "success" and isinstance(res.get("result"), dict):
            r = res["result"]
            picked = {k: r.get(k) for k in keys if r.get(k) is not None}
            if picked:
                res = {**res, "result": picked}
        return res

    return post


def _lean_listing(res: Dict[str, Any], _input: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy list shaping: drop archived/createdAt/updatedAt from each
    result row and the paging.next.link URL (agents only need the cursor)."""
    r = res.get("result")
    if isinstance(r, dict):
        for it in r.get("results") or []:
            if isinstance(it, dict):
                it.pop("archived", None)
                it.pop("createdAt", None)
                it.pop("updatedAt", None)
        nxt = (r.get("paging") or {}).get("next")
        if isinstance(nxt, dict):
            nxt.pop("link", None)
    return res


def _batch_ids(res: Dict[str, Any], _input: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy batch-create shaping: reduce to {ids, numErrors?, errors?}."""
    r = res.get("result")
    if (
        res.get("status") == "success"
        and isinstance(r, dict)
        and isinstance(r.get("results"), list)
    ):
        reduced: Dict[str, Any] = {
            "ids": [i.get("id") for i in r["results"] if isinstance(i, dict)]
        }
        if r.get("numErrors"):
            reduced["numErrors"] = r.get("numErrors")
            reduced["errors"] = r.get("errors")
        res = {**res, "result": reduced}
    return res


def _created_list_id(res: Dict[str, Any], _input: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy create_hubspot_list shaping: reduce to {listId}."""
    r = res.get("result")
    if res.get("status") == "success" and isinstance(r, dict):
        lst = r.get("list") if isinstance(r.get("list"), dict) else r
        list_id = lst.get("listId") or lst.get("id")
        if list_id is not None:
            res = {**res, "result": {"listId": list_id}}
    return res


def _csv(value: Any) -> Optional[List[str]]:
    """Legacy comma-string parsing: 'a, b' → ['a', 'b']; empty → None."""
    return [p.strip() for p in str(value or "").split(",") if p.strip()] or None


# ────────────────────────────────────────────────────────────────────────
# Operations
# ────────────────────────────────────────────────────────────────────────


def build_operations() -> List[Operation]:
    return [
        # ── Contacts ─────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_contacts",
                "list_contacts",
                description=(
                    "List HubSpot contacts. Paginated; pass 'after' from the "
                    "previous response's paging.next.after to get more."
                ),
                tags=("hubspot_contacts", "hubspot"),
                input_schema={
                    "limit": _limit(30, "Max results (1-100, default 30)."),
                    "after": _s("Pagination cursor from previous response.", ""),
                    "properties": _s(
                        "Comma-separated property names to include.",
                        "email,firstname,lastname",
                    ),
                    "archived": _b("Include archived contacts."),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                    "archived": d.get("archived", False),
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_contact",
            "get_contact",
            description=(
                "Get a HubSpot contact by ID. Returns properties and (if "
                "requested) associated objects."
            ),
            tags=("hubspot_contacts", "hubspot"),
            input_schema={
                "contact_id": _s("HubSpot contact ID (numeric string).", "123456789"),
                "properties": _s(
                    "Comma-separated property names to include.",
                    "email,firstname,lastname,phone",
                ),
                "associations": _s(
                    "Comma-separated object types to include associations for.",
                    "companies,deals",
                ),
            },
            arg_map=lambda d: {
                "contact_id": d["contact_id"],
                "properties": _csv(d.get("properties", "")),
                "associations": _csv(d.get("associations", "")),
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_contact",
                "create_contact",
                description=(
                    "Create a HubSpot contact. 'properties' is a flat dict like "
                    "{email, firstname, lastname, phone, company}. Returns only "
                    "{id}."
                ),
                parallelizable=False,
                tags=("hubspot_contacts", "hubspot"),
                input_schema={
                    "properties": _obj(
                        "Flat property dict.",
                        {
                            "email": "jane@example.com",
                            "firstname": "Jane",
                            "lastname": "Doe",
                        },
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {"properties": d["properties"]},
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_contact",
                "update_contact",
                description="Update a HubSpot contact's properties. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_contacts", "hubspot"),
                input_schema={
                    "contact_id": _s("Contact ID.", "123456789"),
                    "properties": _obj(
                        "Properties to update (flat dict).", {"phone": "+1-555-0100"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "contact_id": d["contact_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_contact",
            "delete_contact",
            description=(
                "Archive (soft-delete) a HubSpot contact. The record can be "
                "restored from the trash UI."
            ),
            destructive=True,
            parallelizable=False,
            tags=("hubspot_contacts",),
            input_schema={"contact_id": _s("Contact ID.", "123456789")},
            arg_map=lambda d: {"contact_id": d["contact_id"]},
        ),
        _with_post(
            client_op(
                "search_hubspot_contacts",
                "search_contacts",
                description=(
                    "Search HubSpot contacts. Use 'query' for free-text or "
                    "'filter_groups' for precise property filters (operators: "
                    "EQ, NEQ, GT, GTE, LT, LTE, BETWEEN, IN, NOT_IN, "
                    "CONTAINS_TOKEN, HAS_PROPERTY)."
                ),
                tags=("hubspot_contacts", "hubspot"),
                input_schema={
                    "query": _s(
                        "Free-text search across default searchable properties.",
                        "jane@example.com",
                    ),
                    "filter_groups": _arr(
                        "Filter groups: [{filters: [{propertyName, operator, value}]}].",
                        [
                            {
                                "filters": [
                                    {
                                        "propertyName": "email",
                                        "operator": "EQ",
                                        "value": "jane@example.com",
                                    }
                                ]
                            }
                        ],
                    ),
                    "properties": _s(
                        "Comma-separated properties to return.",
                        "email,firstname,lastname",
                    ),
                    "limit": _limit(30, "Max results (1-100)."),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "query": d.get("query") or None,
                    "filter_groups": d.get("filter_groups") or None,
                    "properties": _csv(d.get("properties", "")),
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "batch_get_hubspot_contacts",
            "batch_get_contacts",
            description="Read up to 100 contacts in a single call. Cheaper than N gets.",
            tags=("hubspot_contacts",),
            input_schema={
                "ids": _arr("Contact IDs.", ["123", "456", "789"]),
                "properties": _s(
                    "Comma-separated properties to return.", "email,firstname"
                ),
            },
            arg_map=lambda d: {
                "ids": d["ids"],
                "properties": _csv(d.get("properties", "")),
            },
        ),
        _with_post(
            client_op(
                "batch_create_hubspot_contacts",
                "batch_create_contacts",
                description=(
                    "Create up to 100 contacts in a single call. 'records' is a "
                    "list of flat property dicts. Returns only the created ids "
                    "(+ errors if any)."
                ),
                parallelizable=False,
                tags=("hubspot_contacts",),
                input_schema={
                    "records": _arr(
                        "List of property dicts.",
                        [{"email": "a@x.com"}, {"email": "b@x.com"}],
                    ),
                },
                output_schema=_only("Only {ids, numErrors?, errors?}."),
                arg_map=lambda d: {"records": d["records"]},
            ),
            _batch_ids,
        ),
        _with_post(
            client_op(
                "merge_hubspot_contacts",
                "merge_contacts",
                description=(
                    "Merge two contacts. The primary contact survives; the "
                    "secondary is archived with associations transferred. "
                    "Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_contacts",),
                input_schema={
                    "primary_id": _s("Contact ID that survives the merge.", "123"),
                    "id_to_merge": _s(
                        "Contact ID that gets merged INTO the primary.", "456"
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "primary_id": d["primary_id"],
                    "id_to_merge": d["id_to_merge"],
                },
            ),
            _pick(["id"]),
        ),
        # ── Companies ────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_companies",
                "list_companies",
                description="List HubSpot companies. Paginated via 'after' cursor.",
                tags=("hubspot_companies", "hubspot"),
                input_schema={
                    "limit": _limit(30, "Max results (1-100)."),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated property names.", "name,domain,industry"
                    ),
                    "archived": _b("Include archived."),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                    "archived": d.get("archived", False),
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_company",
            "get_company",
            description="Get a HubSpot company by ID.",
            tags=("hubspot_companies",),
            input_schema={
                "company_id": _s("Company ID (numeric string).", "123456789"),
                "properties": _s(
                    "Comma-separated properties.", "name,domain,industry,city"
                ),
                "associations": _s(
                    "Comma-separated association types.", "contacts,deals"
                ),
            },
            arg_map=lambda d: {
                "company_id": d["company_id"],
                "properties": _csv(d.get("properties", "")),
                "associations": _csv(d.get("associations", "")),
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_company",
                "create_company",
                description=(
                    "Create a HubSpot company. Typical properties: name, domain, "
                    "industry, city, country. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_companies", "hubspot"),
                input_schema={
                    "properties": _obj(
                        "Flat property dict.", {"name": "Acme Co", "domain": "acme.com"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {"properties": d["properties"]},
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_company",
                "update_company",
                description="Update a HubSpot company's properties. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_companies",),
                input_schema={
                    "company_id": _s("Company ID.", "123456789"),
                    "properties": _obj(
                        "Properties to update.", {"industry": "Software"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "company_id": d["company_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_company",
            "delete_company",
            description="Archive (soft-delete) a HubSpot company.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_companies",),
            input_schema={"company_id": _s("Company ID.", "123456789")},
            arg_map=lambda d: {"company_id": d["company_id"]},
        ),
        _with_post(
            client_op(
                "search_hubspot_companies",
                "search_companies",
                description=(
                    "Search HubSpot companies using query or filter_groups "
                    "(same shape as contact search)."
                ),
                tags=("hubspot_companies", "hubspot"),
                input_schema={
                    "query": _s("Free-text search.", "acme"),
                    "filter_groups": _arr(
                        "Property filter groups.",
                        [
                            {
                                "filters": [
                                    {
                                        "propertyName": "domain",
                                        "operator": "EQ",
                                        "value": "acme.com",
                                    }
                                ]
                            }
                        ],
                    ),
                    "properties": _s(
                        "Comma-separated properties to return.", "name,domain"
                    ),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "query": d.get("query") or None,
                    "filter_groups": d.get("filter_groups") or None,
                    "properties": _csv(d.get("properties", "")),
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "batch_get_hubspot_companies",
            "batch_get_companies",
            description="Read up to 100 companies in a single call.",
            tags=("hubspot_companies",),
            input_schema={
                "ids": _arr("Company IDs.", ["123", "456"]),
                "properties": _s("Comma-separated properties.", "name,domain"),
            },
            arg_map=lambda d: {
                "ids": d["ids"],
                "properties": _csv(d.get("properties", "")),
            },
        ),
        _with_post(
            client_op(
                "batch_create_hubspot_companies",
                "batch_create_companies",
                description=(
                    "Create up to 100 companies in a single call. Returns only "
                    "the created ids (+ errors if any)."
                ),
                parallelizable=False,
                tags=("hubspot_companies",),
                input_schema={
                    "records": _arr(
                        "List of property dicts.", [{"name": "Acme"}, {"name": "Foo"}]
                    ),
                },
                output_schema=_only("Only {ids, numErrors?, errors?}."),
                arg_map=lambda d: {"records": d["records"]},
            ),
            _batch_ids,
        ),
        # ── Deals ────────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_deals",
                "list_deals",
                description="List HubSpot deals. Paginated.",
                tags=("hubspot_deals", "hubspot"),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "dealname,amount,dealstage,pipeline",
                    ),
                    "archived": _b("Include archived."),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                    "archived": d.get("archived", False),
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_deal",
            "get_deal",
            description="Get a HubSpot deal by ID.",
            tags=("hubspot_deals",),
            input_schema={
                "deal_id": _s("Deal ID.", "123456789"),
                "properties": _s(
                    "Comma-separated properties.",
                    "dealname,amount,dealstage,pipeline,closedate",
                ),
                "associations": _s(
                    "Comma-separated association types.", "contacts,companies"
                ),
            },
            arg_map=lambda d: {
                "deal_id": d["deal_id"],
                "properties": _csv(d.get("properties", "")),
                "associations": _csv(d.get("associations", "")),
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_deal",
                "create_deal",
                description=(
                    "Create a HubSpot deal. Typical properties: dealname, "
                    "amount, dealstage, pipeline, closedate, hubspot_owner_id. "
                    "Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_deals", "hubspot"),
                input_schema={
                    "properties": _obj(
                        "Flat property dict.",
                        {
                            "dealname": "Q3 renewal",
                            "amount": "50000",
                            "dealstage": "qualifiedtobuy",
                        },
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {"properties": d["properties"]},
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_deal",
                "update_deal",
                description="Update a HubSpot deal's properties. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_deals", "hubspot"),
                input_schema={
                    "deal_id": _s("Deal ID.", "123456789"),
                    "properties": _obj("Properties to update.", {"amount": "75000"}),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "deal_id": d["deal_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_deal",
            "delete_deal",
            description="Archive (soft-delete) a HubSpot deal.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_deals",),
            input_schema={"deal_id": _s("Deal ID.", "123456789")},
            arg_map=lambda d: {"deal_id": d["deal_id"]},
        ),
        _with_post(
            client_op(
                "search_hubspot_deals",
                "search_deals",
                description="Search HubSpot deals via query or filter_groups.",
                tags=("hubspot_deals",),
                input_schema={
                    "query": _s("Free-text search.", "renewal"),
                    "filter_groups": _arr(
                        "Property filter groups.",
                        [
                            {
                                "filters": [
                                    {
                                        "propertyName": "dealstage",
                                        "operator": "EQ",
                                        "value": "closedwon",
                                    }
                                ]
                            }
                        ],
                    ),
                    "properties": _s("Comma-separated properties.", "dealname,amount"),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "query": d.get("query") or None,
                    "filter_groups": d.get("filter_groups") or None,
                    "properties": _csv(d.get("properties", "")),
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "batch_create_hubspot_deals",
                "batch_create_deals",
                description=(
                    "Create up to 100 deals in a single call. Returns only the "
                    "created ids (+ errors if any)."
                ),
                parallelizable=False,
                tags=("hubspot_deals",),
                input_schema={
                    "records": _arr(
                        "List of property dicts.",
                        [{"dealname": "A"}, {"dealname": "B"}],
                    ),
                },
                output_schema=_only("Only {ids, numErrors?, errors?}."),
                arg_map=lambda d: {"records": d["records"]},
            ),
            _batch_ids,
        ),
        _with_post(
            client_op(
                "move_hubspot_deal_stage",
                "move_deal_stage",
                description=(
                    "Move a deal to a different pipeline stage. Helper around "
                    "updating the 'dealstage' property. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_deals", "hubspot"),
                input_schema={
                    "deal_id": _s("Deal ID.", "123456789"),
                    "stage_id": _s(
                        "Target stage ID (use list_hubspot_pipeline_stages to find).",
                        "closedwon",
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "deal_id": d["deal_id"],
                    "stage_id": d["stage_id"],
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "list_hubspot_deals_by_pipeline",
                "list_deals_by_pipeline",
                description=(
                    "List deals in a specific pipeline. Helper that wraps "
                    "search with a pipeline filter."
                ),
                tags=("hubspot_deals",),
                input_schema={
                    "pipeline_id": _s("Pipeline ID.", "default"),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "pipeline_id": d["pipeline_id"],
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        # ── Tickets ──────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_tickets",
                "list_tickets",
                description="List HubSpot support tickets. Paginated.",
                tags=("hubspot_tickets", "hubspot"),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "subject,content,hs_pipeline_stage,hs_ticket_priority",
                    ),
                    "archived": _b("Include archived."),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                    "archived": d.get("archived", False),
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_ticket",
            "get_ticket",
            description="Get a HubSpot ticket by ID.",
            tags=("hubspot_tickets",),
            input_schema={
                "ticket_id": _s("Ticket ID.", "123456789"),
                "properties": _s(
                    "Comma-separated properties.", "subject,content,hs_pipeline_stage"
                ),
                "associations": _s(
                    "Comma-separated association types.", "contacts,companies"
                ),
            },
            arg_map=lambda d: {
                "ticket_id": d["ticket_id"],
                "properties": _csv(d.get("properties", "")),
                "associations": _csv(d.get("associations", "")),
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_ticket",
                "create_ticket",
                description=(
                    "Create a HubSpot support ticket. Typical properties: "
                    "subject, content, hs_pipeline, hs_pipeline_stage, "
                    "hs_ticket_priority (LOW/MEDIUM/HIGH/URGENT). Returns only "
                    "{id}."
                ),
                parallelizable=False,
                tags=("hubspot_tickets", "hubspot"),
                input_schema={
                    "properties": _obj(
                        "Flat property dict.",
                        {
                            "subject": "Login fails",
                            "content": "User can't log in",
                            "hs_ticket_priority": "HIGH",
                        },
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {"properties": d["properties"]},
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_ticket",
                "update_ticket",
                description="Update a HubSpot ticket's properties. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_tickets",),
                input_schema={
                    "ticket_id": _s("Ticket ID.", "123456789"),
                    "properties": _obj(
                        "Properties to update.", {"hs_ticket_priority": "URGENT"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "ticket_id": d["ticket_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_ticket",
            "delete_ticket",
            description="Archive (soft-delete) a HubSpot ticket.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_tickets",),
            input_schema={"ticket_id": _s("Ticket ID.", "123456789")},
            arg_map=lambda d: {"ticket_id": d["ticket_id"]},
        ),
        _with_post(
            client_op(
                "search_hubspot_tickets",
                "search_tickets",
                description="Search HubSpot tickets via query or filter_groups.",
                tags=("hubspot_tickets",),
                input_schema={
                    "query": _s("Free-text search.", "login"),
                    "filter_groups": _arr(
                        "Filter groups.",
                        [
                            {
                                "filters": [
                                    {
                                        "propertyName": "hs_ticket_priority",
                                        "operator": "EQ",
                                        "value": "HIGH",
                                    }
                                ]
                            }
                        ],
                    ),
                    "properties": _s("Comma-separated properties.", "subject,content"),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "query": d.get("query") or None,
                    "filter_groups": d.get("filter_groups") or None,
                    "properties": _csv(d.get("properties", "")),
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "close_hubspot_ticket",
                "close_ticket",
                description=(
                    "Move a ticket to its closed stage. Helper around updating "
                    "'hs_pipeline_stage'. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_tickets", "hubspot"),
                input_schema={
                    "ticket_id": _s("Ticket ID.", "123456789"),
                    "closed_stage_id": _s(
                        "Closed-stage ID for this pipeline (use "
                        "list_hubspot_pipeline_stages).",
                        "4",
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "ticket_id": d["ticket_id"],
                    "closed_stage_id": d["closed_stage_id"],
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "list_hubspot_tickets_by_pipeline",
                "list_tickets_by_pipeline",
                description="List tickets in a specific pipeline. Helper that wraps search.",
                tags=("hubspot_tickets",),
                input_schema={
                    "pipeline_id": _s("Pipeline ID.", "0"),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "pipeline_id": d["pipeline_id"],
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        # ── Engagements: tasks ───────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_tasks",
                "list_tasks",
                description="List HubSpot tasks (engagements).",
                tags=("hubspot_engagements",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "hs_task_subject,hs_task_status,hs_timestamp",
                    ),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "create_hubspot_task",
                "create_task",
                description=(
                    "Create a HubSpot task. Optionally associate it with a "
                    "contact/company/deal/ticket. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_engagements", "hubspot"),
                input_schema={
                    "subject": _s("Task title.", "Follow up on demo"),
                    "body": _s("Task description.", "Ask about pricing tier"),
                    "due_timestamp_ms": _i("Due date in ms since epoch.", 1735689600000),
                    "owner_id": _s("Owner (user) ID to assign.", "12345"),
                    "priority": _s("NONE | LOW | MEDIUM | HIGH.", "MEDIUM"),
                    "status": _s(
                        "NOT_STARTED | IN_PROGRESS | WAITING | COMPLETED | DEFERRED.",
                        "NOT_STARTED",
                    ),
                    "associated_object_type": _s(
                        "Type of object to associate "
                        "(contacts/companies/deals/tickets).",
                        "contacts",
                    ),
                    "associated_object_id": _s(
                        "ID of the associated object.", "123456789"
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "subject": d["subject"],
                    "body": d.get("body", ""),
                    "due_timestamp_ms": d.get("due_timestamp_ms"),
                    "owner_id": d.get("owner_id") or None,
                    "priority": d.get("priority", "NONE"),
                    "status": d.get("status", "NOT_STARTED"),
                    "associated_object_type": d.get("associated_object_type") or None,
                    "associated_object_id": d.get("associated_object_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_task",
                "update_task",
                description=(
                    "Update a HubSpot task. Common updates: hs_task_status, "
                    "hs_task_priority, hs_task_subject. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_engagements",),
                input_schema={
                    "task_id": _s("Task ID.", "123456789"),
                    "properties": _obj(
                        "Properties to update.", {"hs_task_status": "COMPLETED"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "task_id": d["task_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_task",
            "delete_task",
            description="Archive a HubSpot task.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_engagements",),
            input_schema={"task_id": _s("Task ID.", "123456789")},
            arg_map=lambda d: {"task_id": d["task_id"]},
        ),
        # ── Engagements: notes ───────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_notes",
                "list_notes",
                description="List HubSpot notes (engagements).",
                tags=("hubspot_engagements",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.", "hs_note_body,hs_timestamp"
                    ),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "create_hubspot_note",
                "create_note",
                description=(
                    "Create a HubSpot note (typically attached to a "
                    "contact/company/deal/ticket). Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_engagements", "hubspot"),
                input_schema={
                    "body": _s(
                        "Note content (HTML supported).",
                        "Customer mentioned interest in Enterprise tier",
                    ),
                    "owner_id": _s("Owner ID.", "12345"),
                    "associated_object_type": _s(
                        "contacts/companies/deals/tickets.", "contacts"
                    ),
                    "associated_object_id": _s("ID of associated object.", "123456789"),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "body": d["body"],
                    "owner_id": d.get("owner_id") or None,
                    "associated_object_type": d.get("associated_object_type") or None,
                    "associated_object_id": d.get("associated_object_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_note",
            "delete_note",
            description="Archive a HubSpot note.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_engagements",),
            input_schema={"note_id": _s("Note ID.", "123456789")},
            arg_map=lambda d: {"note_id": d["note_id"]},
        ),
        # ── Engagements: calls ───────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_calls",
                "list_calls",
                description="List HubSpot call engagements (logged calls).",
                tags=("hubspot_engagements",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "hs_call_title,hs_call_duration,hs_call_direction",
                    ),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "log_hubspot_call",
                "log_call",
                description="Log a phone call as a HubSpot engagement. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_engagements", "hubspot"),
                input_schema={
                    "title": _s("Call title.", "Discovery call"),
                    "body": _s("Call notes.", "Discussed pricing"),
                    "timestamp_ms": _i(
                        "When the call happened (ms epoch). Defaults to now.",
                        1735689600000,
                    ),
                    "duration_ms": _i("Call duration in ms.", 600000),
                    "from_number": _s("Caller phone.", "+1-555-0100"),
                    "to_number": _s("Callee phone.", "+1-555-0200"),
                    "direction": _s("INBOUND | OUTBOUND.", "OUTBOUND"),
                    "disposition": _s("Outcome ID (configured per portal).", ""),
                    "owner_id": _s("Owner ID.", "12345"),
                    "associated_object_type": _s(
                        "contacts/companies/deals/tickets.", "contacts"
                    ),
                    "associated_object_id": _s("Associated object ID.", "123456789"),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "title": d["title"],
                    "body": d.get("body", ""),
                    "timestamp_ms": d.get("timestamp_ms"),
                    "duration_ms": d.get("duration_ms"),
                    "from_number": d.get("from_number") or None,
                    "to_number": d.get("to_number") or None,
                    "direction": d.get("direction", "OUTBOUND"),
                    "disposition": d.get("disposition") or None,
                    "owner_id": d.get("owner_id") or None,
                    "associated_object_type": d.get("associated_object_type") or None,
                    "associated_object_id": d.get("associated_object_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        # ── Engagements: emails ──────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_emails",
                "list_emails",
                description=(
                    "List HubSpot email engagements (logged emails — not "
                    "marketing email sends)."
                ),
                tags=("hubspot_engagements",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "hs_email_subject,hs_email_direction",
                    ),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "log_hubspot_email",
                "log_email",
                description=(
                    "Log an email as a HubSpot engagement (for record-keeping; "
                    "doesn't actually send). Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_engagements",),
                input_schema={
                    "subject": _s("Email subject.", "Re: Pricing"),
                    "text_body": _s("Plain-text body.", "Here's the proposal"),
                    "html_body": _s("HTML body (optional).", ""),
                    "timestamp_ms": _i("When sent (ms epoch).", 1735689600000),
                    "direction": _s(
                        "EMAIL (incoming) | INCOMING_EMAIL | FORWARDED_EMAIL.",
                        "EMAIL",
                    ),
                    "from_email": _s("Sender.", "you@yourdomain.com"),
                    "to_email": _s("Recipient.", "customer@example.com"),
                    "owner_id": _s("Owner ID.", "12345"),
                    "associated_object_type": _s(
                        "contacts/companies/deals/tickets.", "contacts"
                    ),
                    "associated_object_id": _s("Associated object ID.", "123456789"),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "subject": d["subject"],
                    "text_body": d.get("text_body", ""),
                    "html_body": d.get("html_body", ""),
                    "timestamp_ms": d.get("timestamp_ms"),
                    "direction": d.get("direction", "EMAIL"),
                    "from_email": d.get("from_email") or None,
                    "to_email": d.get("to_email") or None,
                    "owner_id": d.get("owner_id") or None,
                    "associated_object_type": d.get("associated_object_type") or None,
                    "associated_object_id": d.get("associated_object_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        # ── Engagements: meetings ────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_meetings",
                "list_meetings",
                description="List HubSpot meeting engagements.",
                tags=("hubspot_engagements",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                    "properties": _s(
                        "Comma-separated properties.",
                        "hs_meeting_title,hs_meeting_start_time",
                    ),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                    "properties": _csv(d.get("properties", "")),
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "create_hubspot_meeting",
                "create_meeting",
                description="Create a HubSpot meeting engagement record. Returns only {id}.",
                parallelizable=False,
                tags=("hubspot_engagements",),
                input_schema={
                    "title": _s("Meeting title.", "Quarterly review"),
                    "body": _s("Description / agenda.", "Review Q3 numbers"),
                    "start_timestamp_ms": _i("Start time (ms epoch).", 1735689600000),
                    "end_timestamp_ms": _i("End time (ms epoch).", 1735693200000),
                    "location": _s("Where (URL or address).", "https://zoom.us/j/123"),
                    "meeting_outcome": _s("Outcome ID (configured per portal).", ""),
                    "owner_id": _s("Owner ID.", "12345"),
                    "associated_object_type": _s(
                        "contacts/companies/deals/tickets.", "deals"
                    ),
                    "associated_object_id": _s("Associated object ID.", "123456789"),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "title": d["title"],
                    "body": d.get("body", ""),
                    "start_timestamp_ms": d["start_timestamp_ms"],
                    "end_timestamp_ms": d["end_timestamp_ms"],
                    "location": d.get("location") or None,
                    "meeting_outcome": d.get("meeting_outcome") or None,
                    "owner_id": d.get("owner_id") or None,
                    "associated_object_type": d.get("associated_object_type") or None,
                    "associated_object_id": d.get("associated_object_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_meeting",
            "delete_meeting",
            description="Archive a HubSpot meeting engagement.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_engagements",),
            input_schema={"meeting_id": _s("Meeting ID.", "123456789")},
            arg_map=lambda d: {"meeting_id": d["meeting_id"]},
        ),
        # ── Lists ────────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_lists",
                "list_lists",
                description="List/search HubSpot lists. Optionally filter to specific list IDs.",
                tags=("hubspot_lists",),
                input_schema={
                    "limit": _limit(30, "Max results (1-500)."),
                    "list_ids": _arr("Optional: specific list IDs to fetch.", []),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "list_ids": d.get("list_ids") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_list",
            "get_list",
            description="Get a HubSpot list by ID.",
            tags=("hubspot_lists",),
            input_schema={"list_id": _s("List ID.", "1")},
            arg_map=lambda d: {"list_id": d["list_id"]},
        ),
        _with_post(
            client_op(
                "create_hubspot_list",
                "create_list",
                description=(
                    "Create a HubSpot list. processing_type=MANUAL for static "
                    "(you add contacts yourself); DYNAMIC for filter-based. "
                    "Returns only {listId}."
                ),
                parallelizable=False,
                tags=("hubspot_lists",),
                input_schema={
                    "name": _s("List name.", "Q3 prospects"),
                    "object_type_id": _s(
                        "Object type ID (0-1=contact, 0-2=company, 0-3=deal, "
                        "0-5=ticket).",
                        "0-1",
                    ),
                    "processing_type": _s("MANUAL or DYNAMIC.", "MANUAL"),
                    "filter_branch": _obj("Filter tree for DYNAMIC lists.", {}),
                },
                output_schema=_only("Only {listId}."),
                arg_map=lambda d: {
                    "name": d["name"],
                    "object_type_id": d.get("object_type_id", "0-1"),
                    "processing_type": d.get("processing_type", "MANUAL"),
                    "filter_branch": d.get("filter_branch") or None,
                },
            ),
            _created_list_id,
        ),
        client_op(
            "delete_hubspot_list",
            "delete_list",
            description="Delete a HubSpot list.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_lists",),
            input_schema={"list_id": _s("List ID.", "1")},
            arg_map=lambda d: {"list_id": d["list_id"]},
        ),
        client_op(
            "add_contacts_to_hubspot_list",
            "add_contacts_to_list",
            description="Add contact IDs to a static (MANUAL) list. No-op on DYNAMIC lists.",
            parallelizable=False,
            tags=("hubspot_lists",),
            input_schema={
                "list_id": _s("List ID.", "1"),
                "contact_ids": _arr("Contact IDs to add.", ["123", "456"]),
            },
            arg_map=lambda d: {
                "list_id": d["list_id"],
                "contact_ids": d["contact_ids"],
            },
        ),
        client_op(
            "remove_contacts_from_hubspot_list",
            "remove_contacts_from_list",
            description="Remove contact IDs from a static (MANUAL) list.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_lists",),
            input_schema={
                "list_id": _s("List ID.", "1"),
                "contact_ids": _arr("Contact IDs to remove.", ["123", "456"]),
            },
            arg_map=lambda d: {
                "list_id": d["list_id"],
                "contact_ids": d["contact_ids"],
            },
        ),
        # ── Pipelines ────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_pipelines",
                "list_pipelines",
                description=(
                    "List all pipelines for an object type (typically 'deals' "
                    "or 'tickets')."
                ),
                tags=("hubspot_pipelines",),
                input_schema={
                    "object_type": _s("Object type: deals or tickets.", "deals"),
                },
                arg_map=lambda d: {"object_type": d["object_type"]},
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_pipeline",
            "get_pipeline",
            description="Get a pipeline definition (including stages).",
            tags=("hubspot_pipelines",),
            input_schema={
                "object_type": _s("deals or tickets.", "deals"),
                "pipeline_id": _s("Pipeline ID.", "default"),
            },
            arg_map=lambda d: {
                "object_type": d["object_type"],
                "pipeline_id": d["pipeline_id"],
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_pipeline",
                "create_pipeline",
                description=(
                    "Create a new pipeline. 'stages' is a list of {label, "
                    "displayOrder, metadata:{probability,...}} dicts. Returns "
                    "only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_pipelines",),
                input_schema={
                    "object_type": _s("deals or tickets.", "deals"),
                    "label": _s("Pipeline name.", "Renewals"),
                    "stages": _arr(
                        "Stage definitions.",
                        [
                            {
                                "label": "New",
                                "displayOrder": 0,
                                "metadata": {"probability": "0.1"},
                            }
                        ],
                    ),
                    "display_order": _i("Display order among pipelines.", 0),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "object_type": d["object_type"],
                    "label": d["label"],
                    "stages": d["stages"],
                    "display_order": d.get("display_order", 0),
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "list_hubspot_pipeline_stages",
                "list_pipeline_stages",
                description=(
                    "List the stages of a pipeline. Returns stage IDs needed "
                    "for move_hubspot_deal_stage / close_hubspot_ticket."
                ),
                tags=("hubspot_pipelines",),
                input_schema={
                    "object_type": _s("deals or tickets.", "deals"),
                    "pipeline_id": _s("Pipeline ID.", "default"),
                },
                arg_map=lambda d: {
                    "object_type": d["object_type"],
                    "pipeline_id": d["pipeline_id"],
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "update_hubspot_pipeline_stage",
                "update_pipeline_stage",
                description=(
                    "Update a pipeline stage's properties (label, displayOrder, "
                    "metadata). Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_pipelines",),
                input_schema={
                    "object_type": _s("deals or tickets.", "deals"),
                    "pipeline_id": _s("Pipeline ID.", "default"),
                    "stage_id": _s("Stage ID.", "qualifiedtobuy"),
                    "properties": _obj(
                        "Stage fields to update.", {"label": "Qualified — Buying"}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "object_type": d["object_type"],
                    "pipeline_id": d["pipeline_id"],
                    "stage_id": d["stage_id"],
                    "properties": d["properties"],
                },
            ),
            _pick(["id"]),
        ),
        # ── Owners ───────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_owners",
                "list_owners",
                description=(
                    "List HubSpot users (owners). Use this to find owner IDs "
                    "for assignment."
                ),
                tags=("hubspot_owners", "hubspot"),
                input_schema={
                    "email": _s("Optional: filter to one owner by email.", ""),
                    "limit": _limit(100, "Max results (1-500)."),
                },
                arg_map=lambda d: {
                    "email": d.get("email") or None,
                    "limit": d.get("limit", 100),
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_owner",
            "get_owner",
            description="Get a HubSpot owner (user) by ID.",
            tags=("hubspot_owners",),
            input_schema={"owner_id": _s("Owner ID.", "12345")},
            arg_map=lambda d: {"owner_id": d["owner_id"]},
        ),
        # ── Properties ───────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_properties",
                "list_properties",
                description=(
                    "List all defined properties for an object type. Use this "
                    "to discover custom-field names before reading/writing "
                    "them."
                ),
                tags=("hubspot_properties",),
                input_schema={
                    "object_type": _s(
                        "contacts/companies/deals/tickets or custom schema name.",
                        "contacts",
                    ),
                },
                arg_map=lambda d: {"object_type": d["object_type"]},
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_property",
            "get_property",
            description="Get a property definition (type, options, group).",
            tags=("hubspot_properties",),
            input_schema={
                "object_type": _s("Object type.", "contacts"),
                "property_name": _s("Property internal name.", "firstname"),
            },
            arg_map=lambda d: {
                "object_type": d["object_type"],
                "property_name": d["property_name"],
            },
        ),
        _with_post(
            client_op(
                "create_hubspot_property",
                "create_property",
                description=(
                    "Create a new custom property. 'definition' must include "
                    "name, label, type, fieldType, groupName. Returns only "
                    "{id, name, type}."
                ),
                parallelizable=False,
                tags=("hubspot_properties",),
                input_schema={
                    "object_type": _s("Object type.", "contacts"),
                    "definition": _obj(
                        "Property definition.",
                        {
                            "name": "favorite_color",
                            "label": "Favorite color",
                            "type": "string",
                            "fieldType": "text",
                            "groupName": "contactinformation",
                        },
                    ),
                },
                output_schema=_only("Only {id, name, type}."),
                arg_map=lambda d: {
                    "object_type": d["object_type"],
                    "definition": d["definition"],
                },
            ),
            _pick(["id", "name", "type"]),
        ),
        _with_post(
            client_op(
                "update_hubspot_property",
                "update_property",
                description=(
                    "Update an existing property's definition (label, "
                    "description, options). Returns only {id, name, type}."
                ),
                parallelizable=False,
                tags=("hubspot_properties",),
                input_schema={
                    "object_type": _s("Object type.", "contacts"),
                    "property_name": _s("Property internal name.", "favorite_color"),
                    "definition": _obj(
                        "Fields to update.", {"label": "Color preference"}
                    ),
                },
                output_schema=_only("Only {id, name, type}."),
                arg_map=lambda d: {
                    "object_type": d["object_type"],
                    "property_name": d["property_name"],
                    "definition": d["definition"],
                },
            ),
            _pick(["id", "name", "type"]),
        ),
        client_op(
            "delete_hubspot_property",
            "delete_property",
            description=(
                "Delete a custom property. Built-in HubSpot properties cannot "
                "be deleted."
            ),
            destructive=True,
            parallelizable=False,
            tags=("hubspot_properties",),
            input_schema={
                "object_type": _s("Object type.", "contacts"),
                "property_name": _s("Property internal name.", "favorite_color"),
            },
            arg_map=lambda d: {
                "object_type": d["object_type"],
                "property_name": d["property_name"],
            },
        ),
        _with_post(
            client_op(
                "list_hubspot_property_groups",
                "list_property_groups",
                description=(
                    "List property groups for an object type (the visual "
                    "sections grouping properties in HubSpot UI)."
                ),
                tags=("hubspot_properties",),
                input_schema={
                    "object_type": _s("Object type.", "contacts"),
                },
                arg_map=lambda d: {"object_type": d["object_type"]},
            ),
            _lean_listing,
        ),
        # ── Associations ─────────────────────────────────────────────────
        _with_post(
            client_op(
                "create_hubspot_association",
                "create_association",
                description=(
                    "Link two objects (e.g. attach a contact to a deal). "
                    "Leaves association_type_id empty for the default "
                    "association between the pair. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_associations", "hubspot"),
                input_schema={
                    "from_object_type": _s("Source object type.", "deals"),
                    "from_object_id": _s("Source object ID.", "123"),
                    "to_object_type": _s("Target object type.", "contacts"),
                    "to_object_id": _s("Target object ID.", "456"),
                    "association_type_id": _i(
                        "Optional: specific association type ID (use "
                        "list_hubspot_association_types).",
                        0,
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "from_object_type": d["from_object_type"],
                    "from_object_id": d["from_object_id"],
                    "to_object_type": d["to_object_type"],
                    "to_object_id": d["to_object_id"],
                    "association_type_id": d.get("association_type_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "list_hubspot_associations",
                "list_associations",
                description=(
                    "List all objects of a given type associated with a source "
                    "object."
                ),
                tags=("hubspot_associations",),
                input_schema={
                    "from_object_type": _s("Source object type.", "deals"),
                    "from_object_id": _s("Source object ID.", "123"),
                    "to_object_type": _s("Target object type to look up.", "contacts"),
                    "limit": _limit(100, "Max results (1-500)."),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "from_object_type": d["from_object_type"],
                    "from_object_id": d["from_object_id"],
                    "to_object_type": d["to_object_type"],
                    "limit": d.get("limit", 100),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "delete_hubspot_association",
            "delete_association",
            description="Remove an association between two objects.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_associations",),
            input_schema={
                "from_object_type": _s("Source type.", "deals"),
                "from_object_id": _s("Source ID.", "123"),
                "to_object_type": _s("Target type.", "contacts"),
                "to_object_id": _s("Target ID.", "456"),
            },
            arg_map=lambda d: {
                "from_object_type": d["from_object_type"],
                "from_object_id": d["from_object_id"],
                "to_object_type": d["to_object_type"],
                "to_object_id": d["to_object_id"],
            },
        ),
        _with_post(
            client_op(
                "list_hubspot_association_types",
                "list_association_types",
                description=(
                    "List the available association types between two object "
                    "types (used when you need a specific labeled association)."
                ),
                tags=("hubspot_associations",),
                input_schema={
                    "from_object_type": _s("Source type.", "deals"),
                    "to_object_type": _s("Target type.", "contacts"),
                },
                arg_map=lambda d: {
                    "from_object_type": d["from_object_type"],
                    "to_object_type": d["to_object_type"],
                },
            ),
            _lean_listing,
        ),
        # ── Forms ────────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_forms",
                "list_forms",
                description="List HubSpot forms (marketing v3).",
                tags=("hubspot_forms",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_form",
            "get_form",
            description="Get a HubSpot form definition by ID.",
            tags=("hubspot_forms",),
            input_schema={
                "form_id": _s("Form GUID.", "abc12345-6789-0abc-def0-123456789abc"),
            },
            arg_map=lambda d: {"form_id": d["form_id"]},
        ),
        _with_post(
            client_op(
                "submit_hubspot_form",
                "submit_form",
                description=(
                    "Programmatically submit a HubSpot form. 'fields' is a "
                    "list of {name, value} dicts. Returns only {id}."
                ),
                parallelizable=False,
                tags=("hubspot_forms",),
                input_schema={
                    "portal_id": _s("Portal/hub ID.", "12345678"),
                    "form_guid": _s(
                        "Form GUID.", "abc12345-6789-0abc-def0-123456789abc"
                    ),
                    "fields": _arr(
                        "Form fields to submit.",
                        [
                            {"name": "email", "value": "jane@example.com"},
                            {"name": "firstname", "value": "Jane"},
                        ],
                    ),
                    "context": _obj(
                        "Optional context (hutk, pageUrl, pageName, ipAddress).",
                        {"pageName": "Demo Request"},
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "portal_id": d["portal_id"],
                    "form_guid": d["form_guid"],
                    "fields": d["fields"],
                    "context": d.get("context") or None,
                },
            ),
            _pick(["id"]),
        ),
        _with_post(
            client_op(
                "list_hubspot_form_submissions",
                "list_form_submissions",
                description="List submissions for a HubSpot form.",
                tags=("hubspot_forms",),
                input_schema={
                    "form_guid": _s(
                        "Form GUID.", "abc12345-6789-0abc-def0-123456789abc"
                    ),
                    "limit": _limit(30, "Max results (1-50)."),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "form_guid": d["form_guid"],
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        # ── Marketing email ──────────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_marketing_emails",
                "list_marketing_emails",
                description="List marketing email campaigns.",
                tags=("hubspot_marketing_email",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_marketing_email",
            "get_marketing_email",
            description="Get a marketing email campaign by ID.",
            tags=("hubspot_marketing_email",),
            input_schema={"email_id": _s("Marketing email ID.", "123456789")},
            arg_map=lambda d: {"email_id": d["email_id"]},
        ),
        _with_post(
            client_op(
                "send_hubspot_single_send",
                "send_single_email",
                description=(
                    "Send a one-off transactional email based on a pre-built "
                    "marketing email template. Returns only {id}."
                ),
                destructive=True,  # legacy irreversible — outward-facing send
                parallelizable=False,
                tags=("hubspot_marketing_email", "hubspot"),
                input_schema={
                    "email_id": _s("Marketing email template ID.", "123456789"),
                    "to_email": _s("Recipient email.", "jane@example.com"),
                    "custom_properties": _obj(
                        "Optional template variables.", {"first_name": "Jane"}
                    ),
                    "contact_properties": _obj(
                        "Optional contact-property overrides.", {}
                    ),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "email_id": d["email_id"],
                    "to_email": d["to_email"],
                    "custom_properties": d.get("custom_properties") or None,
                    "contact_properties": d.get("contact_properties") or None,
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "get_hubspot_marketing_email_statistics",
            "get_marketing_email_statistics",
            description="Get aggregated send/open/click statistics for a marketing email.",
            tags=("hubspot_marketing_email",),
            input_schema={"email_id": _s("Marketing email ID.", "123456789")},
            arg_map=lambda d: {"email_id": d["email_id"]},
        ),
        # ── Files ────────────────────────────────────────────────────────
        _with_post(
            client_op(
                "upload_hubspot_file",
                "upload_file",
                description=(
                    "Upload a local file to the HubSpot file manager. 'access' "
                    "controls visibility: PUBLIC_INDEXABLE / "
                    "PUBLIC_NOT_INDEXABLE / HIDDEN / PRIVATE. Returns only "
                    "{id, url}."
                ),
                parallelizable=False,
                tags=("hubspot_files",),
                input_schema={
                    "file_path": _s("Local path to the file.", "/tmp/contract.pdf"),
                    "folder_path": _s("HubSpot folder path.", "/"),
                    "access": _s(
                        "PUBLIC_INDEXABLE | PUBLIC_NOT_INDEXABLE | HIDDEN | "
                        "PRIVATE.",
                        "PRIVATE",
                    ),
                    "overwrite": _b("Overwrite existing file with the same name."),
                },
                output_schema=_only("Only {id, url}."),
                arg_map=lambda d: {
                    "file_path": d["file_path"],
                    "folder_path": d.get("folder_path", "/"),
                    "access": d.get("access", "PRIVATE"),
                    "overwrite": d.get("overwrite", False),
                },
            ),
            _pick(["id", "url"]),
        ),
        client_op(
            "get_hubspot_file",
            "get_file",
            description="Get a file's metadata (including URL).",
            tags=("hubspot_files",),
            input_schema={"file_id": _s("File ID.", "123456789")},
            arg_map=lambda d: {"file_id": d["file_id"]},
        ),
        client_op(
            "delete_hubspot_file",
            "delete_file",
            description="Delete a file from the HubSpot file manager.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_files",),
            input_schema={"file_id": _s("File ID.", "123456789")},
            arg_map=lambda d: {"file_id": d["file_id"]},
        ),
        _with_post(
            client_op(
                "list_hubspot_folders",
                "list_folders",
                description="List folders in the HubSpot file manager.",
                tags=("hubspot_files",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        # ── Conversations (Inbox) ────────────────────────────────────────
        _with_post(
            client_op(
                "list_hubspot_conversations",
                "list_conversations",
                description="List conversation threads in the HubSpot Inbox.",
                tags=("hubspot_conversations",),
                input_schema={
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        client_op(
            "get_hubspot_conversation",
            "get_conversation",
            description="Get a conversation thread by ID.",
            tags=("hubspot_conversations",),
            input_schema={"thread_id": _s("Thread ID.", "123456789")},
            arg_map=lambda d: {"thread_id": d["thread_id"]},
        ),
        _with_post(
            client_op(
                "list_hubspot_conversation_messages",
                "list_conversation_messages",
                description="List messages in a conversation thread.",
                tags=("hubspot_conversations",),
                input_schema={
                    "thread_id": _s("Thread ID.", "123456789"),
                    "limit": _limit(),
                    "after": _after(),
                },
                arg_map=lambda d: {
                    "thread_id": d["thread_id"],
                    "limit": d.get("limit", 30),
                    "after": d.get("after") or None,
                },
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "send_hubspot_conversation_message",
                "send_conversation_message",
                description=(
                    "Send a message into a conversation thread. Requires the "
                    "channel + channel-account IDs from the thread metadata. "
                    "Returns only {id}."
                ),
                destructive=True,  # legacy irreversible — outward-facing send
                parallelizable=False,
                tags=("hubspot_conversations",),
                input_schema={
                    "thread_id": _s("Thread ID.", "123456789"),
                    "text": _s("Message body.", "Thanks for reaching out!"),
                    "channel_id": _s("Channel ID (from thread metadata).", "1000"),
                    "channel_account_id": _s(
                        "Channel account ID (from thread metadata).", "12345"
                    ),
                    "recipients": _arr(
                        "Recipient list [{actorId, "
                        "deliveryIdentifier:{type,value}}].",
                        [
                            {
                                "actorId": "V-123",
                                "deliveryIdentifier": {
                                    "type": "HS_EMAIL_ADDRESS",
                                    "value": "jane@example.com",
                                },
                            }
                        ],
                    ),
                    "sender_actor_id": _s("Optional sender actor ID.", ""),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "thread_id": d["thread_id"],
                    "text": d["text"],
                    "channel_id": d["channel_id"],
                    "channel_account_id": d["channel_account_id"],
                    "recipients": d["recipients"],
                    "sender_actor_id": d.get("sender_actor_id") or None,
                },
            ),
            _pick(["id"]),
        ),
        # ── Webhooks (App-level — requires HubSpot App ID) ───────────────
        _with_post(
            client_op(
                "list_hubspot_webhook_subscriptions",
                "list_webhook_subscriptions",
                description=(
                    "List webhook subscriptions for a HubSpot App. Requires "
                    "the App ID from the developer console."
                ),
                tags=("hubspot_webhooks",),
                input_schema={
                    "app_id": _s("HubSpot App ID (developer console).", "1234567"),
                },
                arg_map=lambda d: {"app_id": d["app_id"]},
            ),
            _lean_listing,
        ),
        _with_post(
            client_op(
                "create_hubspot_webhook_subscription",
                "create_webhook_subscription",
                description=(
                    "Subscribe a HubSpot App to an event type (e.g. "
                    "contact.creation, contact.propertyChange). Returns only "
                    "{id}."
                ),
                parallelizable=False,
                tags=("hubspot_webhooks",),
                input_schema={
                    "app_id": _s("HubSpot App ID.", "1234567"),
                    "event_type": _s(
                        "Event type to subscribe to.", "contact.creation"
                    ),
                    "property_name": _s(
                        "Property name (only for *.propertyChange event types).",
                        "",
                    ),
                    "active": _b("Whether the subscription is active.", True),
                },
                output_schema=_only("Only {id}."),
                arg_map=lambda d: {
                    "app_id": d["app_id"],
                    "event_type": d["event_type"],
                    "property_name": d.get("property_name") or None,
                    "active": d.get("active", True),
                },
            ),
            _pick(["id"]),
        ),
        client_op(
            "delete_hubspot_webhook_subscription",
            "delete_webhook_subscription",
            description="Delete a webhook subscription.",
            destructive=True,
            parallelizable=False,
            tags=("hubspot_webhooks",),
            input_schema={
                "app_id": _s("HubSpot App ID.", "1234567"),
                "subscription_id": _s("Subscription ID.", "abc123"),
            },
            arg_map=lambda d: {
                "app_id": d["app_id"],
                "subscription_id": d["subscription_id"],
            },
        ),
    ]
