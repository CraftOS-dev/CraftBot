"""HubSpot action surface.

Mirrors the HubSpot client in
``craftos_integrations/integrations/hubspot/__init__.py`` 1:1. Sub-sets are
prefixed with ``hubspot_`` per the action_set convention; the ``hubspot``
umbrella tags the high-value 20% the agent should reach for by default.

Identifier shape (always string): HubSpot returns numeric-looking IDs that
overflow JS number range — pass them through as strings. See
``craftos_integrations/integrations/hubspot/INTEGRATION.md`` for the full
gotcha list.
"""

from agent_core import action


# ==================================================================
# Contacts
# ==================================================================


@action(
    name="list_hubspot_contacts",
    description="List HubSpot contacts. Paginated; pass 'after' from the previous response's paging.next.after to get more.",
    action_sets=["hubspot_contacts", "hubspot"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100, default 30).",
            "example": 30,
        },
        "after": {
            "type": "string",
            "description": "Pagination cursor from previous response.",
            "example": "",
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated property names to include.",
            "example": "email,firstname,lastname",
        },
        "archived": {
            "type": "boolean",
            "description": "Include archived contacts.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_contacts(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_contacts",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        archived=input_data.get("archived", False),
    )
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


@action(
    name="get_hubspot_contact",
    description="Get a HubSpot contact by ID. Returns properties and (if requested) associated objects.",
    action_sets=["hubspot_contacts", "hubspot"],
    input_schema={
        "contact_id": {
            "type": "string",
            "description": "HubSpot contact ID (numeric string).",
            "example": "123456789",
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated property names to include.",
            "example": "email,firstname,lastname,phone",
        },
        "associations": {
            "type": "string",
            "description": "Comma-separated object types to include associations for.",
            "example": "companies,deals",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_contact(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    assocs = input_data.get("associations", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_contact",
        account=input_data.get("account"),
        contact_id=input_data["contact_id"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        associations=[a.strip() for a in assocs.split(",") if a.strip()] or None,
    )


@action(
    name="create_hubspot_contact",
    description="Create a HubSpot contact. 'properties' is a flat dict like {email, firstname, lastname, phone, company}. Returns only {id}.",
    action_sets=["hubspot_contacts", "hubspot"],
    input_schema={
        "properties": {
            "type": "object",
            "description": "Flat property dict.",
            "example": {
                "email": "jane@example.com",
                "firstname": "Jane",
                "lastname": "Doe",
            },
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_contact",
        account=input_data.get("account"),
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="update_hubspot_contact",
    description="Update a HubSpot contact's properties. Returns only {id}.",
    action_sets=["hubspot_contacts", "hubspot"],
    input_schema={
        "contact_id": {
            "type": "string",
            "description": "Contact ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update (flat dict).",
            "example": {"phone": "+1-555-0100"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_contact",
        account=input_data.get("account"),
        contact_id=input_data["contact_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_contact",
    description="Archive (soft-delete) a HubSpot contact. The record can be restored from the trash UI.",
    action_sets=["hubspot_contacts"],
    input_schema={
        "contact_id": {
            "type": "string",
            "description": "Contact ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_contact",
        account=input_data.get("account"),
        contact_id=input_data["contact_id"],
    )


@action(
    name="search_hubspot_contacts",
    description="Search HubSpot contacts. Use 'query' for free-text or 'filter_groups' for precise property filters (operators: EQ, NEQ, GT, GTE, LT, LTE, BETWEEN, IN, NOT_IN, CONTAINS_TOKEN, HAS_PROPERTY).",
    action_sets=["hubspot_contacts", "hubspot"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Free-text search across default searchable properties.",
            "example": "jane@example.com",
        },
        "filter_groups": {
            "type": "array",
            "description": "Filter groups: [{filters: [{propertyName, operator, value}]}].",
            "example": [
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
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties to return.",
            "example": "email,firstname,lastname",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 30,
        },
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_hubspot_contacts(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "search_contacts",
        account=input_data.get("account"),
        query=input_data.get("query") or None,
        filter_groups=input_data.get("filter_groups") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="batch_get_hubspot_contacts",
    description="Read up to 100 contacts in a single call. Cheaper than N gets.",
    action_sets=["hubspot_contacts"],
    input_schema={
        "ids": {
            "type": "array",
            "description": "Contact IDs.",
            "example": ["123", "456", "789"],
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties to return.",
            "example": "email,firstname",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def batch_get_hubspot_contacts(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "batch_get_contacts",
        account=input_data.get("account"),
        ids=input_data["ids"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )


@action(
    name="batch_create_hubspot_contacts",
    description="Create up to 100 contacts in a single call. 'records' is a list of flat property dicts. Returns only the created ids (+ errors if any).",
    action_sets=["hubspot_contacts"],
    input_schema={
        "records": {
            "type": "array",
            "description": "List of property dicts.",
            "example": [{"email": "a@x.com"}, {"email": "b@x.com"}],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {ids, numErrors?, errors?}."}},
    parallelizable=False,
)
async def batch_create_hubspot_contacts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "batch_create_contacts",
        account=input_data.get("account"),
        records=input_data["records"],
    )
    r = res.get("result")
    if (
        res.get("status") == "success"
        and isinstance(r, dict)
        and isinstance(r.get("results"), list)
    ):
        reduced = {"ids": [i.get("id") for i in r["results"] if isinstance(i, dict)]}
        if r.get("numErrors"):
            reduced["numErrors"] = r.get("numErrors")
            reduced["errors"] = r.get("errors")
        res = {**res, "result": reduced}
    return res


@action(
    name="merge_hubspot_contacts",
    description="Merge two contacts. The primary contact survives; the secondary is archived with associations transferred. Returns only {id}.",
    action_sets=["hubspot_contacts"],
    input_schema={
        "primary_id": {
            "type": "string",
            "description": "Contact ID that survives the merge.",
            "example": "123",
        },
        "id_to_merge": {
            "type": "string",
            "description": "Contact ID that gets merged INTO the primary.",
            "example": "456",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def merge_hubspot_contacts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "merge_contacts",
        account=input_data.get("account"),
        primary_id=input_data["primary_id"],
        id_to_merge=input_data["id_to_merge"],
    )
    return pick_result(res, ["id"])


# ==================================================================
# Companies
# ==================================================================


@action(
    name="list_hubspot_companies",
    description="List HubSpot companies. Paginated via 'after' cursor.",
    action_sets=["hubspot_companies", "hubspot"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 30,
        },
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated property names.",
            "example": "name,domain,industry",
        },
        "archived": {
            "type": "boolean",
            "description": "Include archived.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_companies(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_companies",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        archived=input_data.get("archived", False),
    )
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


@action(
    name="get_hubspot_company",
    description="Get a HubSpot company by ID.",
    action_sets=["hubspot_companies"],
    input_schema={
        "company_id": {
            "type": "string",
            "description": "Company ID (numeric string).",
            "example": "123456789",
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "name,domain,industry,city",
        },
        "associations": {
            "type": "string",
            "description": "Comma-separated association types.",
            "example": "contacts,deals",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_company(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    assocs = input_data.get("associations", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_company",
        account=input_data.get("account"),
        company_id=input_data["company_id"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        associations=[a.strip() for a in assocs.split(",") if a.strip()] or None,
    )


@action(
    name="create_hubspot_company",
    description="Create a HubSpot company. Typical properties: name, domain, industry, city, country. Returns only {id}.",
    action_sets=["hubspot_companies", "hubspot"],
    input_schema={
        "properties": {
            "type": "object",
            "description": "Flat property dict.",
            "example": {"name": "Acme Co", "domain": "acme.com"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_company(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_company",
        account=input_data.get("account"),
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="update_hubspot_company",
    description="Update a HubSpot company's properties. Returns only {id}.",
    action_sets=["hubspot_companies"],
    input_schema={
        "company_id": {
            "type": "string",
            "description": "Company ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"industry": "Software"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_company(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_company",
        account=input_data.get("account"),
        company_id=input_data["company_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_company",
    description="Archive (soft-delete) a HubSpot company.",
    action_sets=["hubspot_companies"],
    input_schema={
        "company_id": {
            "type": "string",
            "description": "Company ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_company(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_company",
        account=input_data.get("account"),
        company_id=input_data["company_id"],
    )


@action(
    name="search_hubspot_companies",
    description="Search HubSpot companies using query or filter_groups (same shape as contact search).",
    action_sets=["hubspot_companies", "hubspot"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Free-text search.",
            "example": "acme",
        },
        "filter_groups": {
            "type": "array",
            "description": "Property filter groups.",
            "example": [
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
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties to return.",
            "example": "name,domain",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_hubspot_companies(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "search_companies",
        account=input_data.get("account"),
        query=input_data.get("query") or None,
        filter_groups=input_data.get("filter_groups") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="batch_get_hubspot_companies",
    description="Read up to 100 companies in a single call.",
    action_sets=["hubspot_companies"],
    input_schema={
        "ids": {
            "type": "array",
            "description": "Company IDs.",
            "example": ["123", "456"],
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "name,domain",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def batch_get_hubspot_companies(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "batch_get_companies",
        account=input_data.get("account"),
        ids=input_data["ids"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )


@action(
    name="batch_create_hubspot_companies",
    description="Create up to 100 companies in a single call. Returns only the created ids (+ errors if any).",
    action_sets=["hubspot_companies"],
    input_schema={
        "records": {
            "type": "array",
            "description": "List of property dicts.",
            "example": [{"name": "Acme"}, {"name": "Foo"}],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {ids, numErrors?, errors?}."}},
    parallelizable=False,
)
async def batch_create_hubspot_companies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "batch_create_companies",
        account=input_data.get("account"),
        records=input_data["records"],
    )
    r = res.get("result")
    if (
        res.get("status") == "success"
        and isinstance(r, dict)
        and isinstance(r.get("results"), list)
    ):
        reduced = {"ids": [i.get("id") for i in r["results"] if isinstance(i, dict)]}
        if r.get("numErrors"):
            reduced["numErrors"] = r.get("numErrors")
            reduced["errors"] = r.get("errors")
        res = {**res, "result": reduced}
    return res


# ==================================================================
# Deals
# ==================================================================


@action(
    name="list_hubspot_deals",
    description="List HubSpot deals. Paginated.",
    action_sets=["hubspot_deals", "hubspot"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "dealname,amount,dealstage,pipeline",
        },
        "archived": {
            "type": "boolean",
            "description": "Include archived.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_deals(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_deals",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        archived=input_data.get("archived", False),
    )
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


@action(
    name="get_hubspot_deal",
    description="Get a HubSpot deal by ID.",
    action_sets=["hubspot_deals"],
    input_schema={
        "deal_id": {
            "type": "string",
            "description": "Deal ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "dealname,amount,dealstage,pipeline,closedate",
        },
        "associations": {
            "type": "string",
            "description": "Comma-separated association types.",
            "example": "contacts,companies",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_deal(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    assocs = input_data.get("associations", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_deal",
        account=input_data.get("account"),
        deal_id=input_data["deal_id"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        associations=[a.strip() for a in assocs.split(",") if a.strip()] or None,
    )


@action(
    name="create_hubspot_deal",
    description="Create a HubSpot deal. Typical properties: dealname, amount, dealstage, pipeline, closedate, hubspot_owner_id. Returns only {id}.",
    action_sets=["hubspot_deals", "hubspot"],
    input_schema={
        "properties": {
            "type": "object",
            "description": "Flat property dict.",
            "example": {
                "dealname": "Q3 renewal",
                "amount": "50000",
                "dealstage": "qualifiedtobuy",
            },
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_deal(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_deal",
        account=input_data.get("account"),
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="update_hubspot_deal",
    description="Update a HubSpot deal's properties. Returns only {id}.",
    action_sets=["hubspot_deals", "hubspot"],
    input_schema={
        "deal_id": {
            "type": "string",
            "description": "Deal ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"amount": "75000"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_deal(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_deal",
        account=input_data.get("account"),
        deal_id=input_data["deal_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_deal",
    description="Archive (soft-delete) a HubSpot deal.",
    action_sets=["hubspot_deals"],
    input_schema={
        "deal_id": {
            "type": "string",
            "description": "Deal ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_deal(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_deal",
        account=input_data.get("account"),
        deal_id=input_data["deal_id"],
    )


@action(
    name="search_hubspot_deals",
    description="Search HubSpot deals via query or filter_groups.",
    action_sets=["hubspot_deals"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Free-text search.",
            "example": "renewal",
        },
        "filter_groups": {
            "type": "array",
            "description": "Property filter groups.",
            "example": [
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
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "dealname,amount",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_hubspot_deals(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "search_deals",
        account=input_data.get("account"),
        query=input_data.get("query") or None,
        filter_groups=input_data.get("filter_groups") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="batch_create_hubspot_deals",
    description="Create up to 100 deals in a single call. Returns only the created ids (+ errors if any).",
    action_sets=["hubspot_deals"],
    input_schema={
        "records": {
            "type": "array",
            "description": "List of property dicts.",
            "example": [{"dealname": "A"}, {"dealname": "B"}],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {ids, numErrors?, errors?}."}},
    parallelizable=False,
)
async def batch_create_hubspot_deals(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "batch_create_deals",
        account=input_data.get("account"),
        records=input_data["records"],
    )
    r = res.get("result")
    if (
        res.get("status") == "success"
        and isinstance(r, dict)
        and isinstance(r.get("results"), list)
    ):
        reduced = {"ids": [i.get("id") for i in r["results"] if isinstance(i, dict)]}
        if r.get("numErrors"):
            reduced["numErrors"] = r.get("numErrors")
            reduced["errors"] = r.get("errors")
        res = {**res, "result": reduced}
    return res


@action(
    name="move_hubspot_deal_stage",
    description="Move a deal to a different pipeline stage. Helper around updating the 'dealstage' property. Returns only {id}.",
    action_sets=["hubspot_deals", "hubspot"],
    input_schema={
        "deal_id": {
            "type": "string",
            "description": "Deal ID.",
            "example": "123456789",
        },
        "stage_id": {
            "type": "string",
            "description": "Target stage ID (use list_hubspot_pipeline_stages to find).",
            "example": "closedwon",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def move_hubspot_deal_stage(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "move_deal_stage",
        account=input_data.get("account"),
        deal_id=input_data["deal_id"],
        stage_id=input_data["stage_id"],
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_deals_by_pipeline",
    description="List deals in a specific pipeline. Helper that wraps search with a pipeline filter.",
    action_sets=["hubspot_deals"],
    input_schema={
        "pipeline_id": {
            "type": "string",
            "description": "Pipeline ID.",
            "example": "default",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_deals_by_pipeline(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_deals_by_pipeline",
        account=input_data.get("account"),
        pipeline_id=input_data["pipeline_id"],
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


# ==================================================================
# Tickets
# ==================================================================


@action(
    name="list_hubspot_tickets",
    description="List HubSpot support tickets. Paginated.",
    action_sets=["hubspot_tickets", "hubspot"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "subject,content,hs_pipeline_stage,hs_ticket_priority",
        },
        "archived": {
            "type": "boolean",
            "description": "Include archived.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_tickets(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_tickets",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        archived=input_data.get("archived", False),
    )
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


@action(
    name="get_hubspot_ticket",
    description="Get a HubSpot ticket by ID.",
    action_sets=["hubspot_tickets"],
    input_schema={
        "ticket_id": {
            "type": "string",
            "description": "Ticket ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "subject,content,hs_pipeline_stage",
        },
        "associations": {
            "type": "string",
            "description": "Comma-separated association types.",
            "example": "contacts,companies",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_ticket(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    assocs = input_data.get("associations", "")
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_ticket",
        account=input_data.get("account"),
        ticket_id=input_data["ticket_id"],
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        associations=[a.strip() for a in assocs.split(",") if a.strip()] or None,
    )


@action(
    name="create_hubspot_ticket",
    description="Create a HubSpot support ticket. Typical properties: subject, content, hs_pipeline, hs_pipeline_stage, hs_ticket_priority (LOW/MEDIUM/HIGH/URGENT). Returns only {id}.",
    action_sets=["hubspot_tickets", "hubspot"],
    input_schema={
        "properties": {
            "type": "object",
            "description": "Flat property dict.",
            "example": {
                "subject": "Login fails",
                "content": "User can't log in",
                "hs_ticket_priority": "HIGH",
            },
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_ticket(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_ticket",
        account=input_data.get("account"),
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="update_hubspot_ticket",
    description="Update a HubSpot ticket's properties. Returns only {id}.",
    action_sets=["hubspot_tickets"],
    input_schema={
        "ticket_id": {
            "type": "string",
            "description": "Ticket ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"hs_ticket_priority": "URGENT"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_ticket(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_ticket",
        account=input_data.get("account"),
        ticket_id=input_data["ticket_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_ticket",
    description="Archive (soft-delete) a HubSpot ticket.",
    action_sets=["hubspot_tickets"],
    input_schema={
        "ticket_id": {
            "type": "string",
            "description": "Ticket ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_ticket(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_ticket",
        account=input_data.get("account"),
        ticket_id=input_data["ticket_id"],
    )


@action(
    name="search_hubspot_tickets",
    description="Search HubSpot tickets via query or filter_groups.",
    action_sets=["hubspot_tickets"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Free-text search.",
            "example": "login",
        },
        "filter_groups": {
            "type": "array",
            "description": "Filter groups.",
            "example": [
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
        },
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "subject,content",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_hubspot_tickets(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "search_tickets",
        account=input_data.get("account"),
        query=input_data.get("query") or None,
        filter_groups=input_data.get("filter_groups") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="close_hubspot_ticket",
    description="Move a ticket to its closed stage. Helper around updating 'hs_pipeline_stage'. Returns only {id}.",
    action_sets=["hubspot_tickets", "hubspot"],
    input_schema={
        "ticket_id": {
            "type": "string",
            "description": "Ticket ID.",
            "example": "123456789",
        },
        "closed_stage_id": {
            "type": "string",
            "description": "Closed-stage ID for this pipeline (use list_hubspot_pipeline_stages).",
            "example": "4",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def close_hubspot_ticket(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "close_ticket",
        account=input_data.get("account"),
        ticket_id=input_data["ticket_id"],
        closed_stage_id=input_data["closed_stage_id"],
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_tickets_by_pipeline",
    description="List tickets in a specific pipeline. Helper that wraps search.",
    action_sets=["hubspot_tickets"],
    input_schema={
        "pipeline_id": {
            "type": "string",
            "description": "Pipeline ID.",
            "example": "0",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_tickets_by_pipeline(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_tickets_by_pipeline",
        account=input_data.get("account"),
        pipeline_id=input_data["pipeline_id"],
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


# ==================================================================
# Engagements (tasks / notes / calls / emails / meetings)
# ==================================================================


@action(
    name="list_hubspot_tasks",
    description="List HubSpot tasks (engagements).",
    action_sets=["hubspot_engagements"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "hs_task_subject,hs_task_status,hs_timestamp",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_tasks(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_tasks",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )
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


@action(
    name="create_hubspot_task",
    description="Create a HubSpot task. Optionally associate it with a contact/company/deal/ticket. Returns only {id}.",
    action_sets=["hubspot_engagements", "hubspot"],
    input_schema={
        "subject": {
            "type": "string",
            "description": "Task title.",
            "example": "Follow up on demo",
        },
        "body": {
            "type": "string",
            "description": "Task description.",
            "example": "Ask about pricing tier",
        },
        "due_timestamp_ms": {
            "type": "integer",
            "description": "Due date in ms since epoch.",
            "example": 1735689600000,
        },
        "owner_id": {
            "type": "string",
            "description": "Owner (user) ID to assign.",
            "example": "12345",
        },
        "priority": {
            "type": "string",
            "description": "NONE | LOW | MEDIUM | HIGH.",
            "example": "MEDIUM",
        },
        "status": {
            "type": "string",
            "description": "NOT_STARTED | IN_PROGRESS | WAITING | COMPLETED | DEFERRED.",
            "example": "NOT_STARTED",
        },
        "associated_object_type": {
            "type": "string",
            "description": "Type of object to associate (contacts/companies/deals/tickets).",
            "example": "contacts",
        },
        "associated_object_id": {
            "type": "string",
            "description": "ID of the associated object.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_task(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_task",
        account=input_data.get("account"),
        subject=input_data["subject"],
        body=input_data.get("body", ""),
        due_timestamp_ms=input_data.get("due_timestamp_ms"),
        owner_id=input_data.get("owner_id") or None,
        priority=input_data.get("priority", "NONE"),
        status=input_data.get("status", "NOT_STARTED"),
        associated_object_type=input_data.get("associated_object_type") or None,
        associated_object_id=input_data.get("associated_object_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="update_hubspot_task",
    description="Update a HubSpot task. Common updates: hs_task_status, hs_task_priority, hs_task_subject. Returns only {id}.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "task_id": {
            "type": "string",
            "description": "Task ID.",
            "example": "123456789",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"hs_task_status": "COMPLETED"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_task(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_task",
        account=input_data.get("account"),
        task_id=input_data["task_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_task",
    description="Archive a HubSpot task.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "task_id": {
            "type": "string",
            "description": "Task ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_task(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_task",
        account=input_data.get("account"),
        task_id=input_data["task_id"],
    )


@action(
    name="list_hubspot_notes",
    description="List HubSpot notes (engagements).",
    action_sets=["hubspot_engagements"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "hs_note_body,hs_timestamp",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_notes(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_notes",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )
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


@action(
    name="create_hubspot_note",
    description="Create a HubSpot note (typically attached to a contact/company/deal/ticket). Returns only {id}.",
    action_sets=["hubspot_engagements", "hubspot"],
    input_schema={
        "body": {
            "type": "string",
            "description": "Note content (HTML supported).",
            "example": "Customer mentioned interest in Enterprise tier",
        },
        "owner_id": {"type": "string", "description": "Owner ID.", "example": "12345"},
        "associated_object_type": {
            "type": "string",
            "description": "contacts/companies/deals/tickets.",
            "example": "contacts",
        },
        "associated_object_id": {
            "type": "string",
            "description": "ID of associated object.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_note(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_note",
        account=input_data.get("account"),
        body=input_data["body"],
        owner_id=input_data.get("owner_id") or None,
        associated_object_type=input_data.get("associated_object_type") or None,
        associated_object_id=input_data.get("associated_object_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_note",
    description="Archive a HubSpot note.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "note_id": {
            "type": "string",
            "description": "Note ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_note(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_note",
        account=input_data.get("account"),
        note_id=input_data["note_id"],
    )


@action(
    name="list_hubspot_calls",
    description="List HubSpot call engagements (logged calls).",
    action_sets=["hubspot_engagements"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "hs_call_title,hs_call_duration,hs_call_direction",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_calls(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_calls",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )
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


@action(
    name="log_hubspot_call",
    description="Log a phone call as a HubSpot engagement. Returns only {id}.",
    action_sets=["hubspot_engagements", "hubspot"],
    input_schema={
        "title": {
            "type": "string",
            "description": "Call title.",
            "example": "Discovery call",
        },
        "body": {
            "type": "string",
            "description": "Call notes.",
            "example": "Discussed pricing",
        },
        "timestamp_ms": {
            "type": "integer",
            "description": "When the call happened (ms epoch). Defaults to now.",
            "example": 1735689600000,
        },
        "duration_ms": {
            "type": "integer",
            "description": "Call duration in ms.",
            "example": 600000,
        },
        "from_number": {
            "type": "string",
            "description": "Caller phone.",
            "example": "+1-555-0100",
        },
        "to_number": {
            "type": "string",
            "description": "Callee phone.",
            "example": "+1-555-0200",
        },
        "direction": {
            "type": "string",
            "description": "INBOUND | OUTBOUND.",
            "example": "OUTBOUND",
        },
        "disposition": {
            "type": "string",
            "description": "Outcome ID (configured per portal).",
            "example": "",
        },
        "owner_id": {"type": "string", "description": "Owner ID.", "example": "12345"},
        "associated_object_type": {
            "type": "string",
            "description": "contacts/companies/deals/tickets.",
            "example": "contacts",
        },
        "associated_object_id": {
            "type": "string",
            "description": "Associated object ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def log_hubspot_call(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "log_call",
        account=input_data.get("account"),
        title=input_data["title"],
        body=input_data.get("body", ""),
        timestamp_ms=input_data.get("timestamp_ms"),
        duration_ms=input_data.get("duration_ms"),
        from_number=input_data.get("from_number") or None,
        to_number=input_data.get("to_number") or None,
        direction=input_data.get("direction", "OUTBOUND"),
        disposition=input_data.get("disposition") or None,
        owner_id=input_data.get("owner_id") or None,
        associated_object_type=input_data.get("associated_object_type") or None,
        associated_object_id=input_data.get("associated_object_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_emails",
    description="List HubSpot email engagements (logged emails — not marketing email sends).",
    action_sets=["hubspot_engagements"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "hs_email_subject,hs_email_direction",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_emails(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_emails",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )
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


@action(
    name="log_hubspot_email",
    description="Log an email as a HubSpot engagement (for record-keeping; doesn't actually send). Returns only {id}.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "subject": {
            "type": "string",
            "description": "Email subject.",
            "example": "Re: Pricing",
        },
        "text_body": {
            "type": "string",
            "description": "Plain-text body.",
            "example": "Here's the proposal",
        },
        "html_body": {
            "type": "string",
            "description": "HTML body (optional).",
            "example": "",
        },
        "timestamp_ms": {
            "type": "integer",
            "description": "When sent (ms epoch).",
            "example": 1735689600000,
        },
        "direction": {
            "type": "string",
            "description": "EMAIL (incoming) | INCOMING_EMAIL | FORWARDED_EMAIL.",
            "example": "EMAIL",
        },
        "from_email": {
            "type": "string",
            "description": "Sender.",
            "example": "you@yourdomain.com",
        },
        "to_email": {
            "type": "string",
            "description": "Recipient.",
            "example": "customer@example.com",
        },
        "owner_id": {"type": "string", "description": "Owner ID.", "example": "12345"},
        "associated_object_type": {
            "type": "string",
            "description": "contacts/companies/deals/tickets.",
            "example": "contacts",
        },
        "associated_object_id": {
            "type": "string",
            "description": "Associated object ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def log_hubspot_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "log_email",
        account=input_data.get("account"),
        subject=input_data["subject"],
        text_body=input_data.get("text_body", ""),
        html_body=input_data.get("html_body", ""),
        timestamp_ms=input_data.get("timestamp_ms"),
        direction=input_data.get("direction", "EMAIL"),
        from_email=input_data.get("from_email") or None,
        to_email=input_data.get("to_email") or None,
        owner_id=input_data.get("owner_id") or None,
        associated_object_type=input_data.get("associated_object_type") or None,
        associated_object_id=input_data.get("associated_object_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_meetings",
    description="List HubSpot meeting engagements.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "properties": {
            "type": "string",
            "description": "Comma-separated properties.",
            "example": "hs_meeting_title,hs_meeting_start_time",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_meetings(input_data: dict) -> dict:
    props = input_data.get("properties", "")
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_meetings",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
        properties=[p.strip() for p in props.split(",") if p.strip()] or None,
    )
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


@action(
    name="create_hubspot_meeting",
    description="Create a HubSpot meeting engagement record. Returns only {id}.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "title": {
            "type": "string",
            "description": "Meeting title.",
            "example": "Quarterly review",
        },
        "body": {
            "type": "string",
            "description": "Description / agenda.",
            "example": "Review Q3 numbers",
        },
        "start_timestamp_ms": {
            "type": "integer",
            "description": "Start time (ms epoch).",
            "example": 1735689600000,
        },
        "end_timestamp_ms": {
            "type": "integer",
            "description": "End time (ms epoch).",
            "example": 1735693200000,
        },
        "location": {
            "type": "string",
            "description": "Where (URL or address).",
            "example": "https://zoom.us/j/123",
        },
        "meeting_outcome": {
            "type": "string",
            "description": "Outcome ID (configured per portal).",
            "example": "",
        },
        "owner_id": {"type": "string", "description": "Owner ID.", "example": "12345"},
        "associated_object_type": {
            "type": "string",
            "description": "contacts/companies/deals/tickets.",
            "example": "deals",
        },
        "associated_object_id": {
            "type": "string",
            "description": "Associated object ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_meeting(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_meeting",
        account=input_data.get("account"),
        title=input_data["title"],
        body=input_data.get("body", ""),
        start_timestamp_ms=input_data["start_timestamp_ms"],
        end_timestamp_ms=input_data["end_timestamp_ms"],
        location=input_data.get("location") or None,
        meeting_outcome=input_data.get("meeting_outcome") or None,
        owner_id=input_data.get("owner_id") or None,
        associated_object_type=input_data.get("associated_object_type") or None,
        associated_object_id=input_data.get("associated_object_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_meeting",
    description="Archive a HubSpot meeting engagement.",
    action_sets=["hubspot_engagements"],
    input_schema={
        "meeting_id": {
            "type": "string",
            "description": "Meeting ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_meeting(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_meeting",
        account=input_data.get("account"),
        meeting_id=input_data["meeting_id"],
    )


# ==================================================================
# Lists
# ==================================================================


@action(
    name="list_hubspot_lists",
    description="List/search HubSpot lists. Optionally filter to specific list IDs.",
    action_sets=["hubspot_lists"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-500).",
            "example": 30,
        },
        "list_ids": {
            "type": "array",
            "description": "Optional: specific list IDs to fetch.",
            "example": [],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_lists(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_lists",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        list_ids=input_data.get("list_ids") or None,
    )
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


@action(
    name="get_hubspot_list",
    description="Get a HubSpot list by ID.",
    action_sets=["hubspot_lists"],
    input_schema={
        "list_id": {"type": "string", "description": "List ID.", "example": "1"},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_list",
        account=input_data.get("account"),
        list_id=input_data["list_id"],
    )


@action(
    name="create_hubspot_list",
    description="Create a HubSpot list. processing_type=MANUAL for static (you add contacts yourself); DYNAMIC for filter-based. Returns only {listId}.",
    action_sets=["hubspot_lists"],
    input_schema={
        "name": {
            "type": "string",
            "description": "List name.",
            "example": "Q3 prospects",
        },
        "object_type_id": {
            "type": "string",
            "description": "Object type ID (0-1=contact, 0-2=company, 0-3=deal, 0-5=ticket).",
            "example": "0-1",
        },
        "processing_type": {
            "type": "string",
            "description": "MANUAL or DYNAMIC.",
            "example": "MANUAL",
        },
        "filter_branch": {
            "type": "object",
            "description": "Filter tree for DYNAMIC lists.",
            "example": {},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {listId}."}},
    parallelizable=False,
)
async def create_hubspot_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "create_list",
        account=input_data.get("account"),
        name=input_data["name"],
        object_type_id=input_data.get("object_type_id", "0-1"),
        processing_type=input_data.get("processing_type", "MANUAL"),
        filter_branch=input_data.get("filter_branch") or None,
    )
    r = res.get("result")
    if res.get("status") == "success" and isinstance(r, dict):
        lst = r.get("list") if isinstance(r.get("list"), dict) else r
        list_id = lst.get("listId") or lst.get("id")
        if list_id is not None:
            res = {**res, "result": {"listId": list_id}}
    return res


@action(
    name="delete_hubspot_list",
    description="Delete a HubSpot list.",
    action_sets=["hubspot_lists"],
    input_schema={
        "list_id": {"type": "string", "description": "List ID.", "example": "1"},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_list",
        account=input_data.get("account"),
        list_id=input_data["list_id"],
    )


@action(
    name="add_contacts_to_hubspot_list",
    description="Add contact IDs to a static (MANUAL) list. No-op on DYNAMIC lists.",
    action_sets=["hubspot_lists"],
    input_schema={
        "list_id": {"type": "string", "description": "List ID.", "example": "1"},
        "contact_ids": {
            "type": "array",
            "description": "Contact IDs to add.",
            "example": ["123", "456"],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_contacts_to_hubspot_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "add_contacts_to_list",
        account=input_data.get("account"),
        list_id=input_data["list_id"],
        contact_ids=input_data["contact_ids"],
    )


@action(
    name="remove_contacts_from_hubspot_list",
    description="Remove contact IDs from a static (MANUAL) list.",
    action_sets=["hubspot_lists"],
    input_schema={
        "list_id": {"type": "string", "description": "List ID.", "example": "1"},
        "contact_ids": {
            "type": "array",
            "description": "Contact IDs to remove.",
            "example": ["123", "456"],
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_contacts_from_hubspot_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "remove_contacts_from_list",
        account=input_data.get("account"),
        list_id=input_data["list_id"],
        contact_ids=input_data["contact_ids"],
    )


# ==================================================================
# Pipelines
# ==================================================================


@action(
    name="list_hubspot_pipelines",
    description="List all pipelines for an object type (typically 'deals' or 'tickets').",
    action_sets=["hubspot_pipelines"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type: deals or tickets.",
            "example": "deals",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_pipelines(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_pipelines",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
    )
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


@action(
    name="get_hubspot_pipeline",
    description="Get a pipeline definition (including stages).",
    action_sets=["hubspot_pipelines"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "deals or tickets.",
            "example": "deals",
        },
        "pipeline_id": {
            "type": "string",
            "description": "Pipeline ID.",
            "example": "default",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_pipeline(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_pipeline",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        pipeline_id=input_data["pipeline_id"],
    )


@action(
    name="create_hubspot_pipeline",
    description="Create a new pipeline. 'stages' is a list of {label, displayOrder, metadata:{probability,...}} dicts. Returns only {id}.",
    action_sets=["hubspot_pipelines"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "deals or tickets.",
            "example": "deals",
        },
        "label": {
            "type": "string",
            "description": "Pipeline name.",
            "example": "Renewals",
        },
        "stages": {
            "type": "array",
            "description": "Stage definitions.",
            "example": [
                {"label": "New", "displayOrder": 0, "metadata": {"probability": "0.1"}}
            ],
        },
        "display_order": {
            "type": "integer",
            "description": "Display order among pipelines.",
            "example": 0,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_pipeline(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_pipeline",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        label=input_data["label"],
        stages=input_data["stages"],
        display_order=input_data.get("display_order", 0),
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_pipeline_stages",
    description="List the stages of a pipeline. Returns stage IDs needed for move_hubspot_deal_stage / close_hubspot_ticket.",
    action_sets=["hubspot_pipelines"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "deals or tickets.",
            "example": "deals",
        },
        "pipeline_id": {
            "type": "string",
            "description": "Pipeline ID.",
            "example": "default",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_pipeline_stages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_pipeline_stages",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        pipeline_id=input_data["pipeline_id"],
    )
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


@action(
    name="update_hubspot_pipeline_stage",
    description="Update a pipeline stage's properties (label, displayOrder, metadata). Returns only {id}.",
    action_sets=["hubspot_pipelines"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "deals or tickets.",
            "example": "deals",
        },
        "pipeline_id": {
            "type": "string",
            "description": "Pipeline ID.",
            "example": "default",
        },
        "stage_id": {
            "type": "string",
            "description": "Stage ID.",
            "example": "qualifiedtobuy",
        },
        "properties": {
            "type": "object",
            "description": "Stage fields to update.",
            "example": {"label": "Qualified — Buying"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def update_hubspot_pipeline_stage(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_pipeline_stage",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        pipeline_id=input_data["pipeline_id"],
        stage_id=input_data["stage_id"],
        properties=input_data["properties"],
    )
    return pick_result(res, ["id"])


# ==================================================================
# Owners
# ==================================================================


@action(
    name="list_hubspot_owners",
    description="List HubSpot users (owners). Use this to find owner IDs for assignment.",
    action_sets=["hubspot_owners", "hubspot"],
    input_schema={
        "email": {
            "type": "string",
            "description": "Optional: filter to one owner by email.",
            "example": "",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-500).",
            "example": 100,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_owners(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_owners",
        account=input_data.get("account"),
        email=input_data.get("email") or None,
        limit=input_data.get("limit", 100),
    )
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


@action(
    name="get_hubspot_owner",
    description="Get a HubSpot owner (user) by ID.",
    action_sets=["hubspot_owners"],
    input_schema={
        "owner_id": {"type": "string", "description": "Owner ID.", "example": "12345"},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_owner(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_owner",
        account=input_data.get("account"),
        owner_id=input_data["owner_id"],
    )


# ==================================================================
# Properties (custom-field schema management)
# ==================================================================


@action(
    name="list_hubspot_properties",
    description="List all defined properties for an object type. Use this to discover custom-field names before reading/writing them.",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "contacts/companies/deals/tickets or custom schema name.",
            "example": "contacts",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_properties(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_properties",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
    )
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


@action(
    name="get_hubspot_property",
    description="Get a property definition (type, options, group).",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type.",
            "example": "contacts",
        },
        "property_name": {
            "type": "string",
            "description": "Property internal name.",
            "example": "firstname",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_property(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_property",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        property_name=input_data["property_name"],
    )


@action(
    name="create_hubspot_property",
    description="Create a new custom property. 'definition' must include name, label, type, fieldType, groupName. Returns only {id, name, type}.",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type.",
            "example": "contacts",
        },
        "definition": {
            "type": "object",
            "description": "Property definition.",
            "example": {
                "name": "favorite_color",
                "label": "Favorite color",
                "type": "string",
                "fieldType": "text",
                "groupName": "contactinformation",
            },
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id, name, type}."}},
    parallelizable=False,
)
async def create_hubspot_property(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_property",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        definition=input_data["definition"],
    )
    return pick_result(res, ["id", "name", "type"])


@action(
    name="update_hubspot_property",
    description="Update an existing property's definition (label, description, options). Returns only {id, name, type}.",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type.",
            "example": "contacts",
        },
        "property_name": {
            "type": "string",
            "description": "Property internal name.",
            "example": "favorite_color",
        },
        "definition": {
            "type": "object",
            "description": "Fields to update.",
            "example": {"label": "Color preference"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id, name, type}."}},
    parallelizable=False,
)
async def update_hubspot_property(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "update_property",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        property_name=input_data["property_name"],
        definition=input_data["definition"],
    )
    return pick_result(res, ["id", "name", "type"])


@action(
    name="delete_hubspot_property",
    description="Delete a custom property. Built-in HubSpot properties cannot be deleted.",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type.",
            "example": "contacts",
        },
        "property_name": {
            "type": "string",
            "description": "Property internal name.",
            "example": "favorite_color",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_property(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_property",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
        property_name=input_data["property_name"],
    )


@action(
    name="list_hubspot_property_groups",
    description="List property groups for an object type (the visual sections grouping properties in HubSpot UI).",
    action_sets=["hubspot_properties"],
    input_schema={
        "object_type": {
            "type": "string",
            "description": "Object type.",
            "example": "contacts",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_property_groups(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_property_groups",
        account=input_data.get("account"),
        object_type=input_data["object_type"],
    )
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


# ==================================================================
# Associations (object-to-object links)
# ==================================================================


@action(
    name="create_hubspot_association",
    description="Link two objects (e.g. attach a contact to a deal). Leaves association_type_id empty for the default association between the pair. Returns only {id}.",
    action_sets=["hubspot_associations", "hubspot"],
    input_schema={
        "from_object_type": {
            "type": "string",
            "description": "Source object type.",
            "example": "deals",
        },
        "from_object_id": {
            "type": "string",
            "description": "Source object ID.",
            "example": "123",
        },
        "to_object_type": {
            "type": "string",
            "description": "Target object type.",
            "example": "contacts",
        },
        "to_object_id": {
            "type": "string",
            "description": "Target object ID.",
            "example": "456",
        },
        "association_type_id": {
            "type": "integer",
            "description": "Optional: specific association type ID (use list_hubspot_association_types).",
            "example": 0,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_association(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_association",
        account=input_data.get("account"),
        from_object_type=input_data["from_object_type"],
        from_object_id=input_data["from_object_id"],
        to_object_type=input_data["to_object_type"],
        to_object_id=input_data["to_object_id"],
        association_type_id=input_data.get("association_type_id") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_associations",
    description="List all objects of a given type associated with a source object.",
    action_sets=["hubspot_associations"],
    input_schema={
        "from_object_type": {
            "type": "string",
            "description": "Source object type.",
            "example": "deals",
        },
        "from_object_id": {
            "type": "string",
            "description": "Source object ID.",
            "example": "123",
        },
        "to_object_type": {
            "type": "string",
            "description": "Target object type to look up.",
            "example": "contacts",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-500).",
            "example": 100,
        },
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_associations(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_associations",
        account=input_data.get("account"),
        from_object_type=input_data["from_object_type"],
        from_object_id=input_data["from_object_id"],
        to_object_type=input_data["to_object_type"],
        limit=input_data.get("limit", 100),
        after=input_data.get("after") or None,
    )
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


@action(
    name="delete_hubspot_association",
    description="Remove an association between two objects.",
    action_sets=["hubspot_associations"],
    input_schema={
        "from_object_type": {
            "type": "string",
            "description": "Source type.",
            "example": "deals",
        },
        "from_object_id": {
            "type": "string",
            "description": "Source ID.",
            "example": "123",
        },
        "to_object_type": {
            "type": "string",
            "description": "Target type.",
            "example": "contacts",
        },
        "to_object_id": {
            "type": "string",
            "description": "Target ID.",
            "example": "456",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_association(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_association",
        account=input_data.get("account"),
        from_object_type=input_data["from_object_type"],
        from_object_id=input_data["from_object_id"],
        to_object_type=input_data["to_object_type"],
        to_object_id=input_data["to_object_id"],
    )


@action(
    name="list_hubspot_association_types",
    description="List the available association types between two object types (used when you need a specific labeled association).",
    action_sets=["hubspot_associations"],
    input_schema={
        "from_object_type": {
            "type": "string",
            "description": "Source type.",
            "example": "deals",
        },
        "to_object_type": {
            "type": "string",
            "description": "Target type.",
            "example": "contacts",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_association_types(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_association_types",
        account=input_data.get("account"),
        from_object_type=input_data["from_object_type"],
        to_object_type=input_data["to_object_type"],
    )
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


# ==================================================================
# Forms
# ==================================================================


@action(
    name="list_hubspot_forms",
    description="List HubSpot forms (marketing v3).",
    action_sets=["hubspot_forms"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_forms(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_forms",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="get_hubspot_form",
    description="Get a HubSpot form definition by ID.",
    action_sets=["hubspot_forms"],
    input_schema={
        "form_id": {
            "type": "string",
            "description": "Form GUID.",
            "example": "abc12345-6789-0abc-def0-123456789abc",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_form(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_form",
        account=input_data.get("account"),
        form_id=input_data["form_id"],
    )


@action(
    name="submit_hubspot_form",
    description="Programmatically submit a HubSpot form. 'fields' is a list of {name, value} dicts. Returns only {id}.",
    action_sets=["hubspot_forms"],
    input_schema={
        "portal_id": {
            "type": "string",
            "description": "Portal/hub ID.",
            "example": "12345678",
        },
        "form_guid": {
            "type": "string",
            "description": "Form GUID.",
            "example": "abc12345-6789-0abc-def0-123456789abc",
        },
        "fields": {
            "type": "array",
            "description": "Form fields to submit.",
            "example": [
                {"name": "email", "value": "jane@example.com"},
                {"name": "firstname", "value": "Jane"},
            ],
        },
        "context": {
            "type": "object",
            "description": "Optional context (hutk, pageUrl, pageName, ipAddress).",
            "example": {"pageName": "Demo Request"},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def submit_hubspot_form(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "submit_form",
        account=input_data.get("account"),
        portal_id=input_data["portal_id"],
        form_guid=input_data["form_guid"],
        fields=input_data["fields"],
        context=input_data.get("context") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="list_hubspot_form_submissions",
    description="List submissions for a HubSpot form.",
    action_sets=["hubspot_forms"],
    input_schema={
        "form_guid": {
            "type": "string",
            "description": "Form GUID.",
            "example": "abc12345-6789-0abc-def0-123456789abc",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-50).",
            "example": 30,
        },
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_form_submissions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_form_submissions",
        account=input_data.get("account"),
        form_guid=input_data["form_guid"],
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


# ==================================================================
# Marketing email
# ==================================================================


@action(
    name="list_hubspot_marketing_emails",
    description="List marketing email campaigns.",
    action_sets=["hubspot_marketing_email"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_marketing_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_marketing_emails",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="get_hubspot_marketing_email",
    description="Get a marketing email campaign by ID.",
    action_sets=["hubspot_marketing_email"],
    input_schema={
        "email_id": {
            "type": "string",
            "description": "Marketing email ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_marketing_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_marketing_email",
        account=input_data.get("account"),
        email_id=input_data["email_id"],
    )


@action(
    name="send_hubspot_single_send",
    irreversible=True,
    description="Send a one-off transactional email based on a pre-built marketing email template. Returns only {id}.",
    action_sets=["hubspot_marketing_email", "hubspot"],
    input_schema={
        "email_id": {
            "type": "string",
            "description": "Marketing email template ID.",
            "example": "123456789",
        },
        "to_email": {
            "type": "string",
            "description": "Recipient email.",
            "example": "jane@example.com",
        },
        "custom_properties": {
            "type": "object",
            "description": "Optional template variables.",
            "example": {"first_name": "Jane"},
        },
        "contact_properties": {
            "type": "object",
            "description": "Optional contact-property overrides.",
            "example": {},
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def send_hubspot_single_send(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "send_single_email",
        account=input_data.get("account"),
        email_id=input_data["email_id"],
        to_email=input_data["to_email"],
        custom_properties=input_data.get("custom_properties") or None,
        contact_properties=input_data.get("contact_properties") or None,
    )
    return pick_result(res, ["id"])


@action(
    name="get_hubspot_marketing_email_statistics",
    description="Get aggregated send/open/click statistics for a marketing email.",
    action_sets=["hubspot_marketing_email"],
    input_schema={
        "email_id": {
            "type": "string",
            "description": "Marketing email ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_marketing_email_statistics(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_marketing_email_statistics",
        account=input_data.get("account"),
        email_id=input_data["email_id"],
    )


# ==================================================================
# Files
# ==================================================================


@action(
    name="upload_hubspot_file",
    description="Upload a local file to the HubSpot file manager. 'access' controls visibility: PUBLIC_INDEXABLE / PUBLIC_NOT_INDEXABLE / HIDDEN / PRIVATE. Returns only {id, url}.",
    action_sets=["hubspot_files"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Local path to the file.",
            "example": "/tmp/contract.pdf",
        },
        "folder_path": {
            "type": "string",
            "description": "HubSpot folder path.",
            "example": "/",
        },
        "access": {
            "type": "string",
            "description": "PUBLIC_INDEXABLE | PUBLIC_NOT_INDEXABLE | HIDDEN | PRIVATE.",
            "example": "PRIVATE",
        },
        "overwrite": {
            "type": "boolean",
            "description": "Overwrite existing file with the same name.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id, url}."}},
    parallelizable=False,
)
async def upload_hubspot_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "upload_file",
        account=input_data.get("account"),
        file_path=input_data["file_path"],
        folder_path=input_data.get("folder_path", "/"),
        access=input_data.get("access", "PRIVATE"),
        overwrite=input_data.get("overwrite", False),
    )
    return pick_result(res, ["id", "url"])


@action(
    name="get_hubspot_file",
    description="Get a file's metadata (including URL).",
    action_sets=["hubspot_files"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "File ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_file",
        account=input_data.get("account"),
        file_id=input_data["file_id"],
    )


@action(
    name="delete_hubspot_file",
    description="Delete a file from the HubSpot file manager.",
    action_sets=["hubspot_files"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "File ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_file",
        account=input_data.get("account"),
        file_id=input_data["file_id"],
    )


@action(
    name="list_hubspot_folders",
    description="List folders in the HubSpot file manager.",
    action_sets=["hubspot_files"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_folders(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_folders",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


# ==================================================================
# Conversations (Inbox)
# ==================================================================


@action(
    name="list_hubspot_conversations",
    description="List conversation threads in the HubSpot Inbox.",
    action_sets=["hubspot_conversations"],
    input_schema={
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_conversations(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_conversations",
        account=input_data.get("account"),
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="get_hubspot_conversation",
    description="Get a conversation thread by ID.",
    action_sets=["hubspot_conversations"],
    input_schema={
        "thread_id": {
            "type": "string",
            "description": "Thread ID.",
            "example": "123456789",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_hubspot_conversation(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "get_conversation",
        account=input_data.get("account"),
        thread_id=input_data["thread_id"],
    )


@action(
    name="list_hubspot_conversation_messages",
    description="List messages in a conversation thread.",
    action_sets=["hubspot_conversations"],
    input_schema={
        "thread_id": {
            "type": "string",
            "description": "Thread ID.",
            "example": "123456789",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 30},
        "after": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_conversation_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_conversation_messages",
        account=input_data.get("account"),
        thread_id=input_data["thread_id"],
        limit=input_data.get("limit", 30),
        after=input_data.get("after") or None,
    )
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


@action(
    name="send_hubspot_conversation_message",
    irreversible=True,
    description="Send a message into a conversation thread. Requires the channel + channel-account IDs from the thread metadata. Returns only {id}.",
    action_sets=["hubspot_conversations"],
    input_schema={
        "thread_id": {
            "type": "string",
            "description": "Thread ID.",
            "example": "123456789",
        },
        "text": {
            "type": "string",
            "description": "Message body.",
            "example": "Thanks for reaching out!",
        },
        "channel_id": {
            "type": "string",
            "description": "Channel ID (from thread metadata).",
            "example": "1000",
        },
        "channel_account_id": {
            "type": "string",
            "description": "Channel account ID (from thread metadata).",
            "example": "12345",
        },
        "recipients": {
            "type": "array",
            "description": "Recipient list [{actorId, deliveryIdentifier:{type,value}}].",
            "example": [
                {
                    "actorId": "V-123",
                    "deliveryIdentifier": {
                        "type": "HS_EMAIL_ADDRESS",
                        "value": "jane@example.com",
                    },
                }
            ],
        },
        "sender_actor_id": {
            "type": "string",
            "description": "Optional sender actor ID.",
            "example": "",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def send_hubspot_conversation_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "send_conversation_message",
        account=input_data.get("account"),
        thread_id=input_data["thread_id"],
        text=input_data["text"],
        channel_id=input_data["channel_id"],
        channel_account_id=input_data["channel_account_id"],
        recipients=input_data["recipients"],
        sender_actor_id=input_data.get("sender_actor_id") or None,
    )
    return pick_result(res, ["id"])


# ==================================================================
# Webhooks (App-level — requires HubSpot App ID, not portal ID)
# ==================================================================


@action(
    name="list_hubspot_webhook_subscriptions",
    description="List webhook subscriptions for a HubSpot App. Requires the App ID from the developer console.",
    action_sets=["hubspot_webhooks"],
    input_schema={
        "app_id": {
            "type": "string",
            "description": "HubSpot App ID (developer console).",
            "example": "1234567",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_hubspot_webhook_subscriptions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "hubspot",
        "list_webhook_subscriptions",
        account=input_data.get("account"),
        app_id=input_data["app_id"],
    )
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


@action(
    name="create_hubspot_webhook_subscription",
    description="Subscribe a HubSpot App to an event type (e.g. contact.creation, contact.propertyChange). Returns only {id}.",
    action_sets=["hubspot_webhooks"],
    input_schema={
        "app_id": {
            "type": "string",
            "description": "HubSpot App ID.",
            "example": "1234567",
        },
        "event_type": {
            "type": "string",
            "description": "Event type to subscribe to.",
            "example": "contact.creation",
        },
        "property_name": {
            "type": "string",
            "description": "Property name (only for *.propertyChange event types).",
            "example": "",
        },
        "active": {
            "type": "boolean",
            "description": "Whether the subscription is active.",
            "example": True,
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object", "description": "Only {id}."}},
    parallelizable=False,
)
async def create_hubspot_webhook_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "hubspot",
        "create_webhook_subscription",
        account=input_data.get("account"),
        app_id=input_data["app_id"],
        event_type=input_data["event_type"],
        property_name=input_data.get("property_name") or None,
        active=input_data.get("active", True),
    )
    return pick_result(res, ["id"])


@action(
    name="delete_hubspot_webhook_subscription",
    description="Delete a webhook subscription.",
    action_sets=["hubspot_webhooks"],
    input_schema={
        "app_id": {
            "type": "string",
            "description": "HubSpot App ID.",
            "example": "1234567",
        },
        "subscription_id": {
            "type": "string",
            "description": "Subscription ID.",
            "example": "abc123",
        },
        "account": {
            "type": "string",
            "description": "Optional HubSpot portal (hub domain, hub id, or unique fragment, e.g. 'work'). Omit to use the primary portal.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_hubspot_webhook_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "hubspot",
        "delete_webhook_subscription",
        account=input_data.get("account"),
        app_id=input_data["app_id"],
        subscription_id=input_data["subscription_id"],
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# These HubSpot REST categories are admin / niche / non-user-facing and are
# excluded from this action surface. Add them later if a real use case appears.
#
# - Workflows / Automation API
#     Workflow CRUD is admin-heavy and requires deep knowledge of HubSpot's
#     visual builder semantics. The agent should USE existing workflows
#     (via property writes that trigger them), not author new ones.
# - CMS Hub (pages, blogs, themes, modules, HubL templates)
#     Site-author surface, not an agent surface. CraftBot is not a CMS.
# - CTAs (legacy + new)
#     Marketing creative surface; rarely useful for agents.
# - Settings (users, teams, business units, brand kits, integration installs)
#     Admin endpoints. Adding/removing users via an agent is rarely safe.
# - Quotes / Line Items / Products
#     Commerce primitives; complex inter-object dependencies. Skip until a
#     specific use case justifies the surface.
# - Payments / Subscriptions / Invoices (HubSpot Payments)
#     Money-moving operations. Should require an explicit guarded action
#     surface, not a default one.
# - Custom Objects / Custom Object Schemas (definitional)
#     Schema authoring is admin-only and rare. Reading/writing instances
#     of an existing custom object works via the generic /crm/v3/objects/{type}
#     endpoints — already covered.
# - Analytics (events, custom behavioral events, attribution)
#     Analytics ingestion + reporting is a category of its own; not useful
#     for the conversational agent flow.
# - Email Subscriptions / Subscription Preferences
#     Compliance-sensitive; the agent should not be flipping consent bits.
# - Single-Send API for marketing emails (legacy v1)
#     Superseded by /marketing/v3/transactional/single-email/send — exposed.
# - Calling Extensions / Video Conferencing Extensions
#     Provider plugins, not user-facing.
