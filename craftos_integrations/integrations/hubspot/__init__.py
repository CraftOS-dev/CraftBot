# -*- coding: utf-8 -*-
"""HubSpot integration — handler (Private App token + OAuth invite) + client.

HubSpot is a per-portal CRM. Both Private App tokens and OAuth access tokens
are bearer tokens against ``api.hubapi.com``, so the client only has one auth
path. The handler exposes two ways in:

  - ``invite`` — three-legged OAuth flow using a shared CraftBot HubSpot app
    (requires ``HUBSPOT_SHARED_CLIENT_ID`` + ``HUBSPOT_SHARED_CLIENT_SECRET``).
  - ``login`` — paste a Private App token (``pat-na1-...``) from the HubSpot
    portal's developer settings.

See INTEGRATION.md for the identifier shape, pagination model, and known
auth failure modes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    OAuthFlow,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...config import ConfigStore
from ...helpers import Result, arequest
from ...helpers import request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

HUBSPOT_API = "https://api.hubapi.com"
HUBSPOT_FORMS_API = "https://api.hsforms.com"

# All scopes the integration uses across its action surface. Listed
# together so the OAuth consent screen asks once for everything.
HUBSPOT_SCOPES = " ".join(
    [
        "oauth",
        "crm.objects.contacts.read",
        "crm.objects.contacts.write",
        "crm.objects.companies.read",
        "crm.objects.companies.write",
        "crm.objects.deals.read",
        "crm.objects.deals.write",
        "crm.objects.owners.read",
        "crm.schemas.contacts.read",
        "crm.schemas.companies.read",
        "crm.schemas.deals.read",
        "crm.schemas.custom.read",
        "crm.lists.read",
        "crm.lists.write",
        "tickets",
        "forms",
        "files",
        "conversations.read",
        "conversations.write",
        "automation",
    ]
)


@dataclass
class HubSpotCredential:
    # Both Private App tokens and OAuth access tokens are sent as
    # ``Authorization: Bearer <access_token>`` — the client doesn't branch
    # on auth_kind, but we keep the field so /hubspot status can tell the
    # user which path they're on.
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    hub_id: str = ""
    hub_domain: str = ""
    user_email: str = ""
    auth_kind: str = "token"  # "token" | "oauth"


@dataclass
class HubSpotConfig:
    """Post-connect runtime knobs."""

    default_pipeline_id: str = ""
    default_owner_id: str = ""
    watch_object_types: List[str] = field(default_factory=list)


HUBSPOT = IntegrationSpec(
    name="hubspot",
    cred_class=HubSpotCredential,
    cred_file="hubspot.json",
    platform_id="hubspot",
)


# -----------------------------------------------------------------
# Handler — auth flows
# -----------------------------------------------------------------


@register_handler(HUBSPOT.name)
class HubSpotHandler(IntegrationHandler):
    spec = HUBSPOT
    display_name = "HubSpot"
    description = "CRM, marketing, sales, and service hub"
    auth_type = "both"  # OAuth invite + Private App token
    icon = "hubspot"
    connect_help = [
        "OAuth (recommended): click 'Connect via CraftOS' — opens HubSpot to authorize",
        "Token path: open app.hubspot.com → Settings → Integrations → Private Apps",
        "Click 'Create a private app', name it (e.g. 'CraftBot')",
        "Open the 'Scopes' tab and check the scopes the agent needs (CRM read/write at minimum)",
        "Open the 'Auth' tab, copy the access token (starts with 'pat-')",
    ]
    fields = [
        {
            "key": "access_token",
            "label": "Private App Access Token",
            "placeholder": "pat-na1-...",
            "password": True,
        },
    ]
    config_class = HubSpotConfig
    config_fields = [
        {
            "key": "default_pipeline_id",
            "label": "Default deal pipeline",
            "type": "text",
            "placeholder": "default",
            "help": "Deal pipeline ID used when create_hubspot_deal omits 'pipeline'. "
            "Leave empty to fall back to HubSpot's default pipeline.",
        },
        {
            "key": "default_owner_id",
            "label": "Default owner",
            "type": "text",
            "placeholder": "12345678",
            "help": "Owner ID auto-assigned to new contacts / deals / tasks when "
            "the action omits the owner. Use list_hubspot_owners to find IDs.",
        },
        {
            "key": "watch_object_types",
            "label": "Watched object types",
            "type": "list",
            "placeholder": "contact,deal,ticket",
            "help": "Object types the listener polls for changes. Comma-separated. "
            "Leave empty to disable polling.",
        },
    ]

    oauth = OAuthFlow(
        client_id_key="HUBSPOT_SHARED_CLIENT_ID",
        client_secret_key="HUBSPOT_SHARED_CLIENT_SECRET",
        auth_url="https://app.hubspot.com/oauth/authorize",
        token_url=f"{HUBSPOT_API}/oauth/v1/token",
        userinfo_url=None,  # HubSpot has /oauth/v1/access-tokens/<token>, fetched manually below
        scopes=HUBSPOT_SCOPES,
    )

    @property
    def subcommands(self) -> List[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"HubSpot OAuth failed: {result['error']}"

        access_token = result.get("access_token", "")
        refresh_token = result.get("refresh_token", "")
        expires_in = result.get("expires_in", 0) or 0

        # Fetch hub_id + user email from the access-token introspection endpoint.
        info = http_request(
            "GET",
            f"{HUBSPOT_API}/oauth/v1/access-tokens/{access_token}",
            expected=(200,),
        )
        if "error" in info:
            return False, f"HubSpot token introspection failed: {info['error']}"
        meta = info.get("result") or {}

        import time as _time

        save_credential(
            self.spec.cred_file,
            HubSpotCredential(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expiry=_time.time() + expires_in if expires_in else 0.0,
                hub_id=str(meta.get("hub_id", "")),
                hub_domain=meta.get("hub_domain", ""),
                user_email=meta.get("user", ""),
                auth_kind="oauth",
            ),
        )
        label = meta.get("hub_domain") or meta.get("hub_id") or "HubSpot"
        return True, f"HubSpot connected via OAuth: {label}"

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: /hubspot login <private_app_token>\n"
                "Get one at: app.hubspot.com → Settings → Integrations → Private Apps"
            )
        token = args[0].strip()
        if not token.startswith("pat-"):
            return False, "Invalid token. Private App tokens start with 'pat-'."

        # Token introspection works for OAuth tokens; for Private App tokens
        # we ping a cheap endpoint to validate and capture hub_id.
        ping = http_request(
            "GET",
            f"{HUBSPOT_API}/account-info/v3/details",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in ping:
            return False, f"HubSpot auth failed: {ping['error']}"
        meta = ping.get("result") or {}

        save_credential(
            self.spec.cred_file,
            HubSpotCredential(
                access_token=token,
                hub_id=str(meta.get("portalId", "")),
                hub_domain=meta.get("uiDomain", ""),
                auth_kind="token",
            ),
        )
        label = meta.get("uiDomain") or meta.get("portalId") or "HubSpot"
        return True, f"HubSpot connected: {label}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No HubSpot credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed HubSpot credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "HubSpot: Not connected"
        cred = load_credential(self.spec.cred_file, HubSpotCredential)
        if not cred:
            return True, "HubSpot: Not connected"
        label = cred.hub_domain or cred.hub_id or "unknown portal"
        via = "OAuth" if cred.auth_kind == "oauth" else "Private App token"
        email = f" ({cred.user_email})" if cred.user_email else ""
        return True, f"HubSpot: Connected\n  - {label}{email} via {via}"


# -----------------------------------------------------------------
# Client — runtime: REST against api.hubapi.com
# -----------------------------------------------------------------

# Object-type names accepted by /crm/v3/objects/{type}.
_OBJECT_TYPES = (
    "contacts",
    "companies",
    "deals",
    "tickets",
    "tasks",
    "notes",
    "calls",
    "emails",
    "meetings",
)


@register_client
class HubSpotClient(BasePlatformClient):
    spec = HUBSPOT
    PLATFORM_ID = HUBSPOT.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[HubSpotCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> HubSpotCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, HubSpotCredential)
        if self._cred is None:
            raise RuntimeError("No HubSpot credentials. Use /hubspot login first.")
        return self._cred

    def _get_valid_access_token(self) -> str:
        """Return a non-expired access token.

        For OAuth credentials, refreshes lazily when ``token_expiry`` has
        passed. For Private App tokens (``auth_kind == "token"``), there
        is no expiry — return the stored token as-is.
        """
        cred = self._load()
        if (
            cred.auth_kind == "oauth"
            and cred.refresh_token
            and cred.token_expiry
            and time.time() > cred.token_expiry
        ):
            refreshed = self._refresh_access_token()
            if refreshed:
                return refreshed
        return cred.access_token

    def _refresh_access_token(self) -> Optional[str]:
        """Swap the refresh_token for a fresh access_token + expiry.

        Mutates the cached credential in place and re-persists to disk.
        Returns the new access_token, or ``None`` on failure (caller falls
        back to the stale token, which produces a clean 401 from HubSpot
        rather than a silent crash).
        """
        cred = self._load()
        if cred.auth_kind != "oauth" or not cred.refresh_token:
            return None

        client_id = ConfigStore.get_oauth("HUBSPOT_SHARED_CLIENT_ID")
        client_secret = ConfigStore.get_oauth("HUBSPOT_SHARED_CLIENT_SECRET")
        if not client_id or not client_secret:
            logger.warning(
                "[HUBSPOT] Cannot refresh token: HUBSPOT_SHARED_CLIENT_ID/SECRET "
                "not configured. Re-run /hubspot invite to reconnect."
            )
            return None

        result = http_request(
            "POST",
            f"{HUBSPOT_API}/oauth/v1/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": cred.refresh_token,
            },
            expected=(200,),
        )
        if "error" in result:
            logger.warning(
                f"[HUBSPOT] Token refresh failed: {result.get('error')}. "
                "Re-run /hubspot invite to reconnect."
            )
            return None

        data = result.get("result") or {}
        new_token = data.get("access_token")
        if not new_token:
            logger.warning("[HUBSPOT] Token refresh returned no access_token.")
            return None

        cred.access_token = new_token
        # HubSpot sometimes rotates the refresh_token, sometimes doesn't —
        # keep the old one if a new one isn't returned.
        cred.refresh_token = data.get("refresh_token") or cred.refresh_token
        # Refresh 60s before actual expiry to avoid races with in-flight calls.
        cred.token_expiry = time.time() + data.get("expires_in", 1800) - 60
        save_credential(self.spec.cred_file, cred)
        logger.info("[HUBSPOT] Access token refreshed.")
        return new_token

    def _headers(
        self, *, content_type: Optional[str] = "application/json"
    ) -> Dict[str, str]:
        token = self._get_valid_access_token()
        h: Dict[str, str] = {"Authorization": f"Bearer {token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        # Mapped onto creating a note attached to a contact/company/deal/ticket.
        # ``recipient`` shape: "<object_type>:<object_id>" (e.g. "contacts:123").
        if ":" in recipient:
            object_type, object_id = recipient.split(":", 1)
        else:
            object_type, object_id = "contacts", recipient
        return await self.create_note(
            body=text,
            associated_object_type=object_type,
            associated_object_id=object_id,
        )

    # =========================================================
    # Generic CRM-object CRUD (used by per-type wrappers below)
    # =========================================================

    async def _list_objects(
        self,
        object_type: str,
        *,
        limit: int = 30,
        after: Optional[str] = None,
        properties: Optional[List[str]] = None,
        associations: Optional[List[str]] = None,
        archived: bool = False,
    ) -> Result:
        params: Dict[str, Any] = {
            "limit": min(max(limit, 1), 100),
            "archived": archived,
        }
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        if associations:
            params["associations"] = ",".join(associations)
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def _get_object(
        self,
        object_type: str,
        object_id: str,
        *,
        properties: Optional[List[str]] = None,
        associations: Optional[List[str]] = None,
    ) -> Result:
        params: Dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        if associations:
            params["associations"] = ",".join(associations)
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers(content_type=None),
            params=params or None,
        )

    async def _create_object(
        self,
        object_type: str,
        properties: Dict[str, Any],
        *,
        associations: Optional[List[Dict[str, Any]]] = None,
    ) -> Result:
        body: Dict[str, Any] = {"properties": properties}
        if associations:
            body["associations"] = associations
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}",
            headers=self._headers(),
            json=body,
        )

    async def _update_object(
        self,
        object_type: str,
        object_id: str,
        properties: Dict[str, Any],
    ) -> Result:
        return await arequest(
            "PATCH",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers(),
            json={"properties": properties},
        )

    async def _delete_object(self, object_type: str, object_id: str) -> Result:
        # HubSpot returns 204 on archive.
        return await arequest(
            "DELETE",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/{object_id}",
            headers=self._headers(content_type=None),
            expected=(204,),
        )

    async def _search_objects(
        self,
        object_type: str,
        *,
        query: Optional[str] = None,
        filter_groups: Optional[List[Dict[str, Any]]] = None,
        properties: Optional[List[str]] = None,
        sorts: Optional[List[Dict[str, str]]] = None,
        limit: int = 30,
        after: Optional[str] = None,
    ) -> Result:
        body: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if query:
            body["query"] = query
        if filter_groups:
            body["filterGroups"] = filter_groups
        if properties:
            body["properties"] = properties
        if sorts:
            body["sorts"] = sorts
        if after:
            body["after"] = after
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/search",
            headers=self._headers(),
            json=body,
        )

    async def _batch_read(
        self,
        object_type: str,
        ids: List[str],
        *,
        properties: Optional[List[str]] = None,
        id_property: Optional[str] = None,
    ) -> Result:
        inputs = [{"id": i} for i in ids]
        body: Dict[str, Any] = {"inputs": inputs}
        if properties:
            body["properties"] = properties
        if id_property:
            body["idProperty"] = id_property
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/batch/read",
            headers=self._headers(),
            json=body,
        )

    async def _batch_create(
        self, object_type: str, records: List[Dict[str, Any]]
    ) -> Result:
        body = {"inputs": [{"properties": r} for r in records]}
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/batch/create",
            headers=self._headers(),
            json=body,
        )

    async def _batch_update(
        self, object_type: str, records: List[Dict[str, Any]]
    ) -> Result:
        # records: [{"id": "...", "properties": {...}}, ...]
        body = {"inputs": records}
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/{object_type}/batch/update",
            headers=self._headers(),
            json=body,
        )

    # =========================================================
    # Contacts
    # =========================================================

    async def list_contacts(self, **kw) -> Result:
        return await self._list_objects("contacts", **kw)

    async def get_contact(self, contact_id: str, **kw) -> Result:
        return await self._get_object("contacts", contact_id, **kw)

    async def create_contact(self, properties: Dict[str, Any], **kw) -> Result:
        return await self._create_object("contacts", properties, **kw)

    async def update_contact(
        self, contact_id: str, properties: Dict[str, Any]
    ) -> Result:
        return await self._update_object("contacts", contact_id, properties)

    async def delete_contact(self, contact_id: str) -> Result:
        return await self._delete_object("contacts", contact_id)

    async def search_contacts(self, **kw) -> Result:
        return await self._search_objects("contacts", **kw)

    async def batch_get_contacts(self, ids: List[str], **kw) -> Result:
        return await self._batch_read("contacts", ids, **kw)

    async def batch_create_contacts(self, records: List[Dict[str, Any]]) -> Result:
        return await self._batch_create("contacts", records)

    async def merge_contacts(self, primary_id: str, id_to_merge: str) -> Result:
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/objects/contacts/merge",
            headers=self._headers(),
            json={"primaryObjectId": primary_id, "objectIdToMerge": id_to_merge},
        )

    # =========================================================
    # Companies
    # =========================================================

    async def list_companies(self, **kw) -> Result:
        return await self._list_objects("companies", **kw)

    async def get_company(self, company_id: str, **kw) -> Result:
        return await self._get_object("companies", company_id, **kw)

    async def create_company(self, properties: Dict[str, Any], **kw) -> Result:
        return await self._create_object("companies", properties, **kw)

    async def update_company(
        self, company_id: str, properties: Dict[str, Any]
    ) -> Result:
        return await self._update_object("companies", company_id, properties)

    async def delete_company(self, company_id: str) -> Result:
        return await self._delete_object("companies", company_id)

    async def search_companies(self, **kw) -> Result:
        return await self._search_objects("companies", **kw)

    async def batch_get_companies(self, ids: List[str], **kw) -> Result:
        return await self._batch_read("companies", ids, **kw)

    async def batch_create_companies(self, records: List[Dict[str, Any]]) -> Result:
        return await self._batch_create("companies", records)

    # =========================================================
    # Deals
    # =========================================================

    async def list_deals(self, **kw) -> Result:
        return await self._list_objects("deals", **kw)

    async def get_deal(self, deal_id: str, **kw) -> Result:
        return await self._get_object("deals", deal_id, **kw)

    async def create_deal(self, properties: Dict[str, Any], **kw) -> Result:
        return await self._create_object("deals", properties, **kw)

    async def update_deal(self, deal_id: str, properties: Dict[str, Any]) -> Result:
        return await self._update_object("deals", deal_id, properties)

    async def delete_deal(self, deal_id: str) -> Result:
        return await self._delete_object("deals", deal_id)

    async def search_deals(self, **kw) -> Result:
        return await self._search_objects("deals", **kw)

    async def batch_create_deals(self, records: List[Dict[str, Any]]) -> Result:
        return await self._batch_create("deals", records)

    async def move_deal_stage(self, deal_id: str, stage_id: str) -> Result:
        # Helper around the dealstage property — the canonical way to move a
        # deal forward without remembering which property name HubSpot uses.
        return await self._update_object("deals", deal_id, {"dealstage": stage_id})

    async def list_deals_by_pipeline(
        self, pipeline_id: str, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        return await self._search_objects(
            "deals",
            filter_groups=[
                {
                    "filters": [
                        {
                            "propertyName": "pipeline",
                            "operator": "EQ",
                            "value": pipeline_id,
                        }
                    ]
                }
            ],
            limit=limit,
            after=after,
        )

    # =========================================================
    # Tickets
    # =========================================================

    async def list_tickets(self, **kw) -> Result:
        return await self._list_objects("tickets", **kw)

    async def get_ticket(self, ticket_id: str, **kw) -> Result:
        return await self._get_object("tickets", ticket_id, **kw)

    async def create_ticket(self, properties: Dict[str, Any], **kw) -> Result:
        return await self._create_object("tickets", properties, **kw)

    async def update_ticket(self, ticket_id: str, properties: Dict[str, Any]) -> Result:
        return await self._update_object("tickets", ticket_id, properties)

    async def delete_ticket(self, ticket_id: str) -> Result:
        return await self._delete_object("tickets", ticket_id)

    async def search_tickets(self, **kw) -> Result:
        return await self._search_objects("tickets", **kw)

    async def close_ticket(self, ticket_id: str, closed_stage_id: str) -> Result:
        # Helper — "close" is just moving the ticket to its closed stage.
        return await self._update_object(
            "tickets", ticket_id, {"hs_pipeline_stage": closed_stage_id}
        )

    async def list_tickets_by_pipeline(
        self, pipeline_id: str, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        return await self._search_objects(
            "tickets",
            filter_groups=[
                {
                    "filters": [
                        {
                            "propertyName": "hs_pipeline",
                            "operator": "EQ",
                            "value": pipeline_id,
                        }
                    ]
                }
            ],
            limit=limit,
            after=after,
        )

    # =========================================================
    # Engagements (tasks / notes / calls / emails / meetings)
    # =========================================================

    @staticmethod
    def _engagement_associations(
        associated_object_type: Optional[str], associated_object_id: Optional[str]
    ) -> Optional[List[Dict[str, Any]]]:
        if not associated_object_type or not associated_object_id:
            return None
        # Default-association API will infer the right typeId for the pair.
        return [
            {
                "to": {"id": associated_object_id},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        # Engagement→object type IDs vary; using the
                        # "associationTypeId" omitted route forces HubSpot
                        # to pick the canonical default for this pair.
                    }
                ],
            }
        ]

    # ---- Tasks
    async def list_tasks(self, **kw) -> Result:
        return await self._list_objects("tasks", **kw)

    async def create_task(
        self,
        subject: str,
        *,
        body: str = "",
        due_timestamp_ms: Optional[int] = None,
        owner_id: Optional[str] = None,
        priority: str = "NONE",
        status: str = "NOT_STARTED",
        associated_object_type: Optional[str] = None,
        associated_object_id: Optional[str] = None,
    ) -> Result:
        props: Dict[str, Any] = {
            "hs_task_subject": subject,
            "hs_task_body": body,
            "hs_task_priority": priority,
            "hs_task_status": status,
        }
        if due_timestamp_ms is not None:
            props["hs_timestamp"] = due_timestamp_ms
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return await self._create_object(
            "tasks",
            props,
            associations=self._engagement_associations(
                associated_object_type, associated_object_id
            ),
        )

    async def update_task(self, task_id: str, properties: Dict[str, Any]) -> Result:
        return await self._update_object("tasks", task_id, properties)

    async def delete_task(self, task_id: str) -> Result:
        return await self._delete_object("tasks", task_id)

    # ---- Notes
    async def list_notes(self, **kw) -> Result:
        return await self._list_objects("notes", **kw)

    async def create_note(
        self,
        body: str,
        *,
        owner_id: Optional[str] = None,
        associated_object_type: Optional[str] = None,
        associated_object_id: Optional[str] = None,
    ) -> Result:
        import time as _t

        props: Dict[str, Any] = {
            "hs_note_body": body,
            "hs_timestamp": int(_t.time() * 1000),
        }
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return await self._create_object(
            "notes",
            props,
            associations=self._engagement_associations(
                associated_object_type, associated_object_id
            ),
        )

    async def delete_note(self, note_id: str) -> Result:
        return await self._delete_object("notes", note_id)

    # ---- Calls
    async def list_calls(self, **kw) -> Result:
        return await self._list_objects("calls", **kw)

    async def log_call(
        self,
        *,
        title: str,
        body: str = "",
        timestamp_ms: Optional[int] = None,
        duration_ms: Optional[int] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
        direction: str = "OUTBOUND",
        disposition: Optional[str] = None,
        owner_id: Optional[str] = None,
        associated_object_type: Optional[str] = None,
        associated_object_id: Optional[str] = None,
    ) -> Result:
        import time as _t

        props: Dict[str, Any] = {
            "hs_call_title": title,
            "hs_call_body": body,
            "hs_call_direction": direction,
            "hs_timestamp": timestamp_ms or int(_t.time() * 1000),
        }
        if duration_ms is not None:
            props["hs_call_duration"] = duration_ms
        if from_number:
            props["hs_call_from_number"] = from_number
        if to_number:
            props["hs_call_to_number"] = to_number
        if disposition:
            props["hs_call_disposition"] = disposition
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return await self._create_object(
            "calls",
            props,
            associations=self._engagement_associations(
                associated_object_type, associated_object_id
            ),
        )

    # ---- Emails (engagement records, not transactional sends)
    async def list_emails(self, **kw) -> Result:
        return await self._list_objects("emails", **kw)

    async def log_email(
        self,
        *,
        subject: str,
        text_body: str = "",
        html_body: str = "",
        timestamp_ms: Optional[int] = None,
        direction: str = "EMAIL",
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        owner_id: Optional[str] = None,
        associated_object_type: Optional[str] = None,
        associated_object_id: Optional[str] = None,
    ) -> Result:
        import time as _t

        props: Dict[str, Any] = {
            "hs_email_subject": subject,
            "hs_email_text": text_body,
            "hs_email_direction": direction,
            "hs_timestamp": timestamp_ms or int(_t.time() * 1000),
        }
        if html_body:
            props["hs_email_html"] = html_body
        if from_email:
            props["hs_email_from_email"] = from_email
        if to_email:
            props["hs_email_to_email"] = to_email
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return await self._create_object(
            "emails",
            props,
            associations=self._engagement_associations(
                associated_object_type, associated_object_id
            ),
        )

    # ---- Meetings
    async def list_meetings(self, **kw) -> Result:
        return await self._list_objects("meetings", **kw)

    async def create_meeting(
        self,
        *,
        title: str,
        body: str = "",
        start_timestamp_ms: int,
        end_timestamp_ms: int,
        location: Optional[str] = None,
        meeting_outcome: Optional[str] = None,
        owner_id: Optional[str] = None,
        associated_object_type: Optional[str] = None,
        associated_object_id: Optional[str] = None,
    ) -> Result:
        props: Dict[str, Any] = {
            "hs_meeting_title": title,
            "hs_meeting_body": body,
            "hs_meeting_start_time": start_timestamp_ms,
            "hs_meeting_end_time": end_timestamp_ms,
            "hs_timestamp": start_timestamp_ms,
        }
        if location:
            props["hs_meeting_location"] = location
        if meeting_outcome:
            props["hs_meeting_outcome"] = meeting_outcome
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        return await self._create_object(
            "meetings",
            props,
            associations=self._engagement_associations(
                associated_object_type, associated_object_id
            ),
        )

    async def delete_meeting(self, meeting_id: str) -> Result:
        return await self._delete_object("meetings", meeting_id)

    # =========================================================
    # Lists (v3 Lists API)
    # =========================================================

    async def list_lists(
        self, *, limit: int = 30, list_ids: Optional[List[str]] = None
    ) -> Result:
        body: Dict[str, Any] = {"count": min(max(limit, 1), 500)}
        if list_ids:
            body["listIds"] = list_ids
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/lists/search",
            headers=self._headers(),
            json=body,
        )

    async def get_list(self, list_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/lists/{list_id}",
            headers=self._headers(content_type=None),
        )

    async def create_list(
        self,
        *,
        name: str,
        object_type_id: str = "0-1",  # 0-1 = contact
        processing_type: str = "MANUAL",  # MANUAL = static, DYNAMIC = filter-based
        filter_branch: Optional[Dict[str, Any]] = None,
    ) -> Result:
        body: Dict[str, Any] = {
            "name": name,
            "objectTypeId": object_type_id,
            "processingType": processing_type,
        }
        if filter_branch:
            body["filterBranch"] = filter_branch
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/lists",
            headers=self._headers(),
            json=body,
        )

    async def delete_list(self, list_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{HUBSPOT_API}/crm/v3/lists/{list_id}",
            headers=self._headers(content_type=None),
            expected=(204,),
        )

    async def add_contacts_to_list(
        self, list_id: str, contact_ids: List[str]
    ) -> Result:
        return await arequest(
            "PUT",
            f"{HUBSPOT_API}/crm/v3/lists/{list_id}/memberships/add",
            headers=self._headers(),
            json=contact_ids,
        )

    async def remove_contacts_from_list(
        self, list_id: str, contact_ids: List[str]
    ) -> Result:
        return await arequest(
            "PUT",
            f"{HUBSPOT_API}/crm/v3/lists/{list_id}/memberships/remove",
            headers=self._headers(),
            json=contact_ids,
        )

    # =========================================================
    # Pipelines
    # =========================================================

    async def list_pipelines(self, object_type: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/pipelines/{object_type}",
            headers=self._headers(content_type=None),
        )

    async def get_pipeline(self, object_type: str, pipeline_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/pipelines/{object_type}/{pipeline_id}",
            headers=self._headers(content_type=None),
        )

    async def create_pipeline(
        self,
        object_type: str,
        *,
        label: str,
        stages: List[Dict[str, Any]],
        display_order: int = 0,
    ) -> Result:
        body = {
            "label": label,
            "displayOrder": display_order,
            "stages": stages,
        }
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/pipelines/{object_type}",
            headers=self._headers(),
            json=body,
        )

    async def list_pipeline_stages(self, object_type: str, pipeline_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/pipelines/{object_type}/{pipeline_id}/stages",
            headers=self._headers(content_type=None),
        )

    async def update_pipeline_stage(
        self,
        object_type: str,
        pipeline_id: str,
        stage_id: str,
        properties: Dict[str, Any],
    ) -> Result:
        return await arequest(
            "PATCH",
            f"{HUBSPOT_API}/crm/v3/pipelines/{object_type}/{pipeline_id}/stages/{stage_id}",
            headers=self._headers(),
            json=properties,
        )

    # =========================================================
    # Owners
    # =========================================================

    async def list_owners(
        self, *, email: Optional[str] = None, limit: int = 100
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 500)}
        if email:
            params["email"] = email
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/owners",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def get_owner(self, owner_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/owners/{owner_id}",
            headers=self._headers(content_type=None),
        )

    # =========================================================
    # Properties (per object type)
    # =========================================================

    async def list_properties(self, object_type: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}",
            headers=self._headers(content_type=None),
        )

    async def get_property(self, object_type: str, property_name: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}/{property_name}",
            headers=self._headers(content_type=None),
        )

    async def create_property(
        self, object_type: str, definition: Dict[str, Any]
    ) -> Result:
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}",
            headers=self._headers(),
            json=definition,
        )

    async def update_property(
        self,
        object_type: str,
        property_name: str,
        definition: Dict[str, Any],
    ) -> Result:
        return await arequest(
            "PATCH",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}/{property_name}",
            headers=self._headers(),
            json=definition,
        )

    async def delete_property(self, object_type: str, property_name: str) -> Result:
        return await arequest(
            "DELETE",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}/{property_name}",
            headers=self._headers(content_type=None),
            expected=(204,),
        )

    async def list_property_groups(self, object_type: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v3/properties/{object_type}/groups",
            headers=self._headers(content_type=None),
        )

    # =========================================================
    # Associations (v4)
    # =========================================================

    async def create_association(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
        *,
        association_category: str = "HUBSPOT_DEFINED",
        association_type_id: Optional[int] = None,
    ) -> Result:
        if association_type_id is None:
            # Default association — HubSpot picks the canonical type for the pair.
            return await arequest(
                "PUT",
                (
                    f"{HUBSPOT_API}/crm/v4/objects/{from_object_type}/{from_object_id}"
                    f"/associations/default/{to_object_type}/{to_object_id}"
                ),
                headers=self._headers(content_type=None),
            )
        return await arequest(
            "PUT",
            (
                f"{HUBSPOT_API}/crm/v4/objects/{from_object_type}/{from_object_id}"
                f"/associations/{to_object_type}/{to_object_id}"
            ),
            headers=self._headers(),
            json=[
                {
                    "associationCategory": association_category,
                    "associationTypeId": association_type_id,
                }
            ],
        )

    async def list_associations(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        *,
        limit: int = 100,
        after: Optional[str] = None,
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 500)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            (
                f"{HUBSPOT_API}/crm/v4/objects/{from_object_type}/{from_object_id}"
                f"/associations/{to_object_type}"
            ),
            headers=self._headers(content_type=None),
            params=params,
        )

    async def delete_association(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
    ) -> Result:
        return await arequest(
            "DELETE",
            (
                f"{HUBSPOT_API}/crm/v4/objects/{from_object_type}/{from_object_id}"
                f"/associations/{to_object_type}/{to_object_id}"
            ),
            headers=self._headers(content_type=None),
            expected=(204,),
        )

    async def list_association_types(
        self, from_object_type: str, to_object_type: str
    ) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/crm/v4/associations/{from_object_type}/{to_object_type}/labels",
            headers=self._headers(content_type=None),
        )

    # =========================================================
    # Forms
    # =========================================================

    async def list_forms(
        self, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/marketing/v3/forms",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def get_form(self, form_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/marketing/v3/forms/{form_id}",
            headers=self._headers(content_type=None),
        )

    async def submit_form(
        self,
        portal_id: str,
        form_guid: str,
        fields: List[Dict[str, Any]],
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Result:
        # Form submissions go to a different host and don't take auth — just
        # the portal_id/form_guid combo. We send anyway via httpx for consistency.
        body: Dict[str, Any] = {"fields": fields}
        if context:
            body["context"] = context
        return await arequest(
            "POST",
            f"{HUBSPOT_FORMS_API}/submissions/v3/integration/submit/{portal_id}/{form_guid}",
            json=body,
            expected=(200,),
        )

    async def list_form_submissions(
        self, form_guid: str, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 50)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/form-integrations/v1/submissions/forms/{form_guid}",
            headers=self._headers(content_type=None),
            params=params,
        )

    # =========================================================
    # Marketing email
    # =========================================================

    async def list_marketing_emails(
        self, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/marketing/v3/emails",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def get_marketing_email(self, email_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/marketing/v3/emails/{email_id}",
            headers=self._headers(content_type=None),
        )

    async def send_single_email(
        self,
        *,
        email_id: str,
        to_email: str,
        custom_properties: Optional[Dict[str, Any]] = None,
        contact_properties: Optional[Dict[str, Any]] = None,
    ) -> Result:
        body: Dict[str, Any] = {
            "emailId": email_id,
            "message": {"to": to_email},
        }
        if custom_properties:
            body["customProperties"] = [
                {"name": k, "value": v} for k, v in custom_properties.items()
            ]
        if contact_properties:
            body["contactProperties"] = [
                {"name": k, "value": v} for k, v in contact_properties.items()
            ]
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/marketing/v3/transactional/single-email/send",
            headers=self._headers(),
            json=body,
        )

    async def get_marketing_email_statistics(self, email_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/marketing/v3/emails/{email_id}/statistics",
            headers=self._headers(content_type=None),
        )

    # =========================================================
    # Files
    # =========================================================

    async def upload_file(
        self,
        file_path: str,
        *,
        folder_path: str = "/",
        access: str = "PUBLIC_INDEXABLE",
        overwrite: bool = False,
    ) -> Result:
        import os as _os

        if not _os.path.isfile(file_path):
            return {"error": f"file not found: {file_path}"}
        options = {
            "access": access,
            "overwrite": overwrite,
        }
        with open(file_path, "rb") as fh:
            files = {
                "file": (_os.path.basename(file_path), fh.read()),
            }
            data = {
                "folderPath": folder_path,
                "options": str(options).replace("'", '"'),
            }
            # Multipart upload — http.request handles this via files=.
            # Use _get_valid_access_token so OAuth creds auto-refresh.
            token = self._get_valid_access_token()
            return await arequest(
                "POST",
                f"{HUBSPOT_API}/files/v3/files",
                headers={"Authorization": f"Bearer {token}"},
                data=data,
                files=files,
            )

    async def get_file(self, file_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/files/v3/files/{file_id}",
            headers=self._headers(content_type=None),
        )

    async def delete_file(self, file_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{HUBSPOT_API}/files/v3/files/{file_id}",
            headers=self._headers(content_type=None),
            expected=(204,),
        )

    async def list_folders(
        self, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/files/v3/folders",
            headers=self._headers(content_type=None),
            params=params,
        )

    # =========================================================
    # Conversations (Inbox)
    # =========================================================

    async def list_conversations(
        self, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/conversations/v3/conversations/threads",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def get_conversation(self, thread_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/conversations/v3/conversations/threads/{thread_id}",
            headers=self._headers(content_type=None),
        )

    async def list_conversation_messages(
        self, thread_id: str, *, limit: int = 30, after: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 100)}
        if after:
            params["after"] = after
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/conversations/v3/conversations/threads/{thread_id}/messages",
            headers=self._headers(content_type=None),
            params=params,
        )

    async def send_conversation_message(
        self,
        thread_id: str,
        *,
        text: str,
        channel_id: str,
        channel_account_id: str,
        recipients: List[Dict[str, Any]],
        sender_actor_id: Optional[str] = None,
    ) -> Result:
        body: Dict[str, Any] = {
            "type": "MESSAGE",
            "text": text,
            "channelId": channel_id,
            "channelAccountId": channel_account_id,
            "recipients": recipients,
        }
        if sender_actor_id:
            body["senderActorId"] = sender_actor_id
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/conversations/v3/conversations/threads/{thread_id}/messages",
            headers=self._headers(),
            json=body,
        )

    # =========================================================
    # Webhooks (requires HubSpot App + appId — see INTEGRATION.md)
    # =========================================================

    async def list_webhook_subscriptions(self, app_id: str) -> Result:
        return await arequest(
            "GET",
            f"{HUBSPOT_API}/webhooks/v3/{app_id}/subscriptions",
            headers=self._headers(content_type=None),
        )

    async def create_webhook_subscription(
        self,
        app_id: str,
        *,
        event_type: str,
        property_name: Optional[str] = None,
        active: bool = True,
    ) -> Result:
        body: Dict[str, Any] = {
            "eventType": event_type,
            "active": active,
        }
        if property_name:
            body["propertyName"] = property_name
        return await arequest(
            "POST",
            f"{HUBSPOT_API}/webhooks/v3/{app_id}/subscriptions",
            headers=self._headers(),
            json=body,
        )

    async def delete_webhook_subscription(
        self, app_id: str, subscription_id: str
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{HUBSPOT_API}/webhooks/v3/{app_id}/subscriptions/{subscription_id}",
            headers=self._headers(content_type=None),
            expected=(204,),
        )
