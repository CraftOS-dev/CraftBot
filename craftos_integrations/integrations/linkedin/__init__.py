# -*- coding: utf-8 -*-
"""LinkedIn integration - handler (OAuth) + client."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    OAuthFlow,
    load_credential,
    register_client,
    register_handler,
    save_credential,
)
from ... import accounts as acc
from ...config import ConfigStore
from ...helpers import Result, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_OAUTH_BASE = "https://www.linkedin.com/oauth/v2"

# Multi-account: the bare "linkedin.json" is always the primary account (no
# migration needed for existing single-account installs); additional
# accounts get "linkedin__<identity>.json" — see craftos_integrations/accounts.py.
_STEM = "linkedin"


def _identity(cred: "LinkedInCredential") -> str:
    # email is the human-friendly identity when available; older credential
    # files (saved before this field existed) fall back to the opaque
    # OpenID `sub` claim so they keep resolving correctly.
    return cred.email or cred.linkedin_id


@dataclass
class LinkedInCredential:
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    client_id: str = ""
    client_secret: str = ""
    linkedin_id: str = ""
    user_id: str = ""
    email: str = ""


LINKEDIN = IntegrationSpec(
    name="linkedin",
    cred_class=LinkedInCredential,
    cred_file="linkedin.json",
    platform_id="linkedin",
)


def _encode_urn(urn: str) -> str:
    return quote(urn, safe="")


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(LINKEDIN.name)
class LinkedInHandler(IntegrationHandler):
    spec = LINKEDIN
    display_name = "LinkedIn"
    description = "Professional network"
    auth_type = "oauth"
    icon = "linkedin"
    connect_help = [
        "Click 'Sign in with LinkedIn' below",
        "A browser tab will open at linkedin.com/oauth - sign in with your LinkedIn account",
        "Approve the requested permissions (read profile, post on behalf, etc.)",
        "You'll be redirected back to CraftBot once consent completes",
    ]
    fields: List = []

    oauth = OAuthFlow(
        client_id_key="LINKEDIN_CLIENT_ID",
        client_secret_key="LINKEDIN_CLIENT_SECRET",
        auth_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        userinfo_url="https://api.linkedin.com/v2/userinfo",
        scopes="openid profile email w_member_social",
        # prompt=login forces LinkedIn's login form every time instead of
        # silently reusing an already-signed-in browser session — the
        # closest LinkedIn equivalent to Google's prompt=select_account.
        # Without it, "add account" would just re-authenticate the same
        # member and overwrite it instead of letting the user switch.
        extra_auth_params={"prompt": "login"},
    )

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"LinkedIn OAuth failed: {result['error']}"

        info = result.get("userinfo", {})
        email = info.get("email", "")
        linkedin_id = info.get("sub", "")
        identity = email or linkedin_id

        target_file = acc.resolve_save_target(_STEM, LinkedInCredential, _identity, identity)
        save_credential(
            target_file,
            LinkedInCredential(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + result.get("expires_in", 3600),
                client_id=ConfigStore.get_oauth("LINKEDIN_CLIENT_ID"),
                client_secret=ConfigStore.get_oauth("LINKEDIN_CLIENT_SECRET"),
                linkedin_id=linkedin_id,
                user_id=linkedin_id,
                email=email,
            ),
        )
        return True, f"LinkedIn connected as {info.get('name')} ({email})"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        account = args[0] if args else None
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, LinkedInCredential, _identity)
        if not accounts:
            return False, "No LinkedIn credentials found."
        if not account:
            acc.remove_all_accounts(_STEM)
            return True, "Removed LinkedIn credential."
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, LinkedInCredential, _identity, account, "LinkedIn"
        )
        if err:
            return False, err
        acc.remove_account(_STEM, fname)
        return True, "Removed LinkedIn account."

    async def status(self) -> Tuple[bool, str]:
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, LinkedInCredential, _identity)
        if not accounts:
            return True, "LinkedIn: Not connected"
        lines = ["LinkedIn: Connected"]
        lines.extend(f"  - {a.identity} ({a.identity})" for a in accounts)
        return True, "\n".join(lines)

    def list_accounts(self):
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, LinkedInCredential, _identity)
        return acc.accounts_to_dicts(accounts)

    async def set_primary(self, account_id: str) -> Tuple[bool, str]:
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, LinkedInCredential, _identity, account_id, "LinkedIn"
        )
        if err:
            return False, err
        if not acc.promote_to_primary(_STEM, fname):
            return False, f"{account_id} is already the primary LinkedIn account."
        return True, f"{account_id} is now the primary LinkedIn account."

    def set_alias(self, account_id: str, alias: str) -> Tuple[bool, str]:
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, LinkedInCredential, _identity, account_id, "LinkedIn"
        )
        if err:
            return False, err
        cred = load_credential(fname, LinkedInCredential)
        if not cred:
            return False, f"Could not load credential for {account_id}."
        acc.set_alias(self.spec.platform_id, _identity(cred), alias)
        return True, f"Alias {'set' if alias.strip() else 'cleared'} for {_identity(cred)}."


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class LinkedInClient(BasePlatformClient):
    spec = LINKEDIN
    PLATFORM_ID = LINKEDIN.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[LinkedInCredential] = None
        self._cred_file: Optional[str] = None

    def has_credentials(self) -> bool:
        """True if *any* account is connected. Deliberately does not resolve
        self._account here — see GoogleApiClientMixin.has_credentials for why."""
        return bool(acc.list_accounts(self.spec.platform_id, _STEM, LinkedInCredential, _identity))

    def _load(self) -> LinkedInCredential:
        if self._cred is None:
            fname, err = acc.resolve_account(
                self.spec.platform_id,
                _STEM,
                LinkedInCredential,
                _identity,
                getattr(self, "_account", None),
                "LinkedIn",
            )
            if err:
                raise RuntimeError(err)
            self._cred_file = fname
            self._cred = load_credential(fname, LinkedInCredential)
        if self._cred is None:
            raise RuntimeError("No LinkedIn credentials. Use /linkedin login first.")
        return self._cred

    def _ensure_token(self) -> str:
        cred = self._load()
        if cred.refresh_token and cred.token_expiry and time.time() > cred.token_expiry:
            result = self.refresh_access_token()
            if result:
                return result
        return cred.access_token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202401",
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        cred = self._load()
        sender_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else ""
        return self.send_message_to_recipients(
            sender_urn=sender_urn,
            recipient_urns=[recipient],
            subject=kwargs.get("subject", ""),
            body=text,
        )

    def refresh_access_token(self) -> Optional[str]:
        cred = self._load()
        if not all([cred.client_id, cred.client_secret, cred.refresh_token]):
            return None
        result = http_request(
            "POST",
            f"{LINKEDIN_OAUTH_BASE}/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": cred.refresh_token,
                "client_id": cred.client_id,
                "client_secret": cred.client_secret,
            },
            expected=(200,),
        )
        if "error" in result:
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        cred.token_expiry = time.time() + data.get("expires_in", 5184000) - 86400
        save_credential(self._cred_file or self.spec.cred_file, cred)
        self._cred = cred
        return cred.access_token

    # --- Profile ---
    def get_user_profile(self) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/userinfo",
            headers={"Authorization": f"Bearer {self._ensure_token()}"},
            expected=(200,),
            transform=lambda d: {
                "linkedin_id": d.get("sub"),
                "name": d.get("name"),
                "given_name": d.get("given_name"),
                "family_name": d.get("family_name"),
                "email": d.get("email"),
                "picture": d.get("picture"),
            },
        )

    def get_profile_details(self) -> Result:
        return http_request(
            "GET", f"{LINKEDIN_API_BASE}/me", headers=self._headers(), expected=(200,)
        )

    # --- Connections ---
    def get_connections(self, count: int = 50, start: int = 0) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/connections",
            headers=self._headers(),
            params={"q": "viewer", "count": min(count, 50), "start": start},
            expected=(200,),
        )

    # --- Search ---
    def search_people(self, keywords: str, count: int = 25, start: int = 0) -> Result:
        result = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/people",
            headers=self._headers(),
            params={
                "q": "search",
                "keywords": keywords,
                "count": min(count, 50),
                "start": start,
            },
            expected=(200,),
        )
        if "error" in result:
            result["note"] = "People search may require specific API access."
        return result

    def search_jobs(
        self,
        keywords: str,
        location: Optional[str] = None,
        count: int = 25,
        start: int = 0,
    ) -> Result:
        params: Dict[str, Any] = {
            "keywords": keywords,
            "count": min(count, 50),
            "start": start,
        }
        if location:
            params["locationGeoUrn"] = location
        result = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/jobSearch",
            headers=self._headers(),
            params=params,
            expected=(200,),
        )
        if "error" in result:
            result["note"] = "LinkedIn Job Search API access may be restricted."
        return result

    def get_job_details(self, job_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/jobs/{job_id}",
            headers=self._headers(),
            expected=(200,),
        )

    def search_companies(
        self, keywords: str, count: int = 25, start: int = 0
    ) -> Result:
        result = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizationLookup",
            headers=self._headers(),
            params={"q": "vanityName", "vanityName": keywords},
            expected=(200,),
        )
        if "ok" in result:
            return result
        alt = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizations",
            headers=self._headers(),
            params={
                "q": "search",
                "keywords": keywords,
                "count": min(count, 50),
                "start": start,
            },
            expected=(200,),
        )
        return alt if "ok" in alt else result

    def get_company_by_vanity_name(self, vanity_name: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizations",
            headers=self._headers(),
            params={"q": "vanityName", "vanityName": vanity_name},
            expected=(200,),
        )

    def get_person(self, person_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/people/(id:{person_id})",
            headers=self._headers(),
            expected=(200,),
        )

    # --- Organizations ---
    def get_my_organizations(self) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizationAcls",
            headers=self._headers(),
            params={
                "q": "roleAssignee",
                "role": "ADMINISTRATOR",
                "projection": "(elements*(organization~,roleAssignee))",
            },
            expected=(200,),
        )

    def get_organization(self, organization_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizations/{organization_id}",
            headers=self._headers(),
            expected=(200,),
        )

    def get_organization_followers_count(self, organization_urn: str) -> Result:
        org_id = (
            organization_urn.split(":")[-1]
            if ":" in organization_urn
            else organization_urn
        )
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizationalEntityFollowerStatistics",
            headers=self._headers(),
            params={
                "q": "organizationalEntity",
                "organizationalEntity": f"urn:li:organization:{org_id}",
            },
            expected=(200,),
        )

    # --- Posts ---
    def _post_ugc(self, payload: Dict[str, Any]) -> Result:
        return http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/ugcPosts",
            headers=self._headers(),
            json=payload,
        )

    def _share_payload(
        self,
        author_urn: str,
        text: str,
        media_category: str,
        media: Optional[List[Dict[str, Any]]] = None,
        visibility: str = "PUBLIC",
    ) -> Dict[str, Any]:
        share: Dict[str, Any] = {
            "shareCommentary": {"text": text[:3000] if text else ""},
            "shareMediaCategory": media_category,
        }
        if media:
            share["media"] = media
        return {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }

    def create_text_post(
        self, author_urn: str, text: str, visibility: str = "PUBLIC"
    ) -> Result:
        return self._post_ugc(
            self._share_payload(author_urn, text, "NONE", visibility=visibility)
        )

    def create_article_post(
        self,
        author_urn: str,
        text: str,
        link_url: str,
        link_title: str = "",
        link_description: str = "",
        visibility: str = "PUBLIC",
    ) -> Result:
        media_item: Dict[str, Any] = {"status": "READY", "originalUrl": link_url}
        if link_title:
            media_item["title"] = {"text": link_title}
        if link_description:
            media_item["description"] = {"text": link_description}
        return self._post_ugc(
            self._share_payload(author_urn, text, "ARTICLE", [media_item], visibility)
        )

    def create_image_post(
        self,
        author_urn: str,
        text: str,
        image_url: str,
        image_title: str = "",
        visibility: str = "PUBLIC",
    ) -> Result:
        media = [
            {
                "status": "READY",
                "originalUrl": image_url,
                "title": {"text": image_title or ""},
            }
        ]
        return self._post_ugc(
            self._share_payload(author_urn, text, "IMAGE", media, visibility)
        )

    def reshare_post(
        self,
        author_urn: str,
        original_post_urn: str,
        commentary: str = "",
        visibility: str = "PUBLIC",
    ) -> Result:
        media = [
            {
                "status": "READY",
                "originalUrl": f"https://www.linkedin.com/feed/update/{original_post_urn}",
            }
        ]
        return self._post_ugc(
            self._share_payload(author_urn, commentary, "ARTICLE", media, visibility)
        )

    def delete_post(self, post_urn: str) -> Result:
        return http_request(
            "DELETE",
            f"{LINKEDIN_API_BASE}/ugcPosts/{_encode_urn(post_urn)}",
            headers=self._headers(),
            expected=(200, 204),
            transform=lambda _d: {"deleted": True},
        )

    def get_post(self, post_urn: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/ugcPosts/{_encode_urn(post_urn)}",
            headers=self._headers(),
            expected=(200,),
        )

    def get_posts_by_author(
        self, author_urn: str, count: int = 50, start: int = 0
    ) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/ugcPosts",
            headers=self._headers(),
            params={
                "q": "authors",
                "authors": f"List({author_urn})",
                "count": min(count, 100),
                "start": start,
            },
            expected=(200,),
        )

    # --- Messaging ---
    def send_message_to_recipients(
        self, sender_urn: str, recipient_urns: List[str], subject: str, body: str
    ) -> Result:
        result = http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/messages",
            headers=self._headers(),
            json={"recipients": recipient_urns, "subject": subject, "body": body},
        )
        if "error" in result:
            result["note"] = "Messaging API requires special permissions."
        elif result.get("result") is None:
            result["result"] = {"sent": True}
        return result

    # --- Invitations ---
    def send_connection_request(
        self, invitee_profile_urn: str, message: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {"invitee": invitee_profile_urn}
        if message:
            payload["message"] = message[:300]
        result = http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/invitations",
            headers=self._headers(),
            json=payload,
        )
        if "ok" in result and result.get("result") is None:
            result["result"] = {"sent": True}
        return result

    def withdraw_connection_request(self, invitation_urn: str) -> Result:
        return http_request(
            "DELETE",
            f"{LINKEDIN_API_BASE}/invitations/{_encode_urn(invitation_urn)}",
            headers=self._headers(),
            expected=(200, 204),
            transform=lambda _d: {"withdrawn": True},
        )

    def get_sent_invitations(self, count: int = 50, start: int = 0) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/invitations",
            headers=self._headers(),
            params={"q": "inviter", "count": min(count, 50), "start": start},
            expected=(200,),
        )

    def get_received_invitations(self, count: int = 50, start: int = 0) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/invitations",
            headers=self._headers(),
            params={"q": "invitee", "count": min(count, 50), "start": start},
            expected=(200,),
        )

    def respond_to_invitation(self, invitation_urn: str, action: str) -> Result:
        return http_request(
            "PATCH",
            f"{LINKEDIN_API_BASE}/invitations/{_encode_urn(invitation_urn)}",
            headers=self._headers(),
            json={"action": action.upper()},
            expected=(200, 204),
            transform=lambda _d: {"action": action, "completed": True},
        )

    # --- Conversations ---
    def get_conversations(self, count: int = 20, start: int = 0) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/conversations",
            headers=self._headers(),
            params={"count": min(count, 50), "start": start},
            expected=(200,),
        )

    # --- Likes ---
    def like_post(self, actor_urn: str, post_urn: str) -> Result:
        result = http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes",
            headers=self._headers(),
            json={"actor": actor_urn},
        )
        if "ok" in result and result.get("result") is None:
            result["result"] = {"liked": True}
        return result

    def unlike_post(self, actor_urn: str, post_urn: str) -> Result:
        composite_key = quote(f"(liker:{actor_urn})", safe="")
        return http_request(
            "DELETE",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes/{composite_key}",
            headers=self._headers(),
            expected=(200, 204),
            transform=lambda _d: {"unliked": True},
        )

    def get_post_reactions(
        self, post_urn: str, count: int = 50, start: int = 0
    ) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes",
            headers=self._headers(),
            params={"count": min(count, 100), "start": start},
            expected=(200,),
        )

    # --- Comments ---
    def comment_on_post(
        self,
        actor_urn: str,
        post_urn: str,
        text: str,
        parent_comment_urn: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"actor": actor_urn, "message": {"text": text[:1250]}}
        if parent_comment_urn:
            payload["parentComment"] = parent_comment_urn
        return http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments",
            headers=self._headers(),
            json=payload,
        )

    def get_post_comments(
        self, post_urn: str, count: int = 50, start: int = 0
    ) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments",
            headers=self._headers(),
            params={"count": min(count, 100), "start": start},
            expected=(200,),
        )

    def delete_comment(self, actor_urn: str, post_urn: str, comment_urn: str) -> Result:
        return http_request(
            "DELETE",
            f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments/{_encode_urn(comment_urn)}",
            headers=self._headers(),
            params={"actor": actor_urn},
            expected=(200, 204),
            transform=lambda _d: {"deleted": True},
        )

    # --- Analytics ---
    def get_post_analytics(self, share_urns: List[str]) -> Result:
        primary = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics",
            headers=self._headers(),
            params={"q": "organizationalEntity", "shares": ",".join(share_urns)},
            expected=(200,),
        )
        if "ok" in primary:
            return primary
        alt = http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/socialMetadata",
            headers=self._headers(),
            params={"ids": f"List({','.join(share_urns)})"},
            expected=(200,),
        )
        return alt if "ok" in alt else primary

    def get_social_metadata(self, post_urn: str) -> Result:
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/socialMetadata/{_encode_urn(post_urn)}",
            headers=self._headers(),
            expected=(200,),
        )

    def get_organization_analytics(self, organization_urn: str) -> Result:
        org_id = (
            organization_urn.split(":")[-1]
            if ":" in organization_urn
            else organization_urn
        )
        return http_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizationPageStatistics",
            headers=self._headers(),
            params={
                "q": "organization",
                "organization": f"urn:li:organization:{org_id}",
            },
            expected=(200,),
        )

    # --- Follow ---
    def follow_organization(self, follower_urn: str, organization_urn: str) -> Result:
        org_id = (
            organization_urn.split(":")[-1]
            if ":" in organization_urn
            else organization_urn
        )
        result = http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/organizationFollows",
            headers=self._headers(),
            json={
                "followee": f"urn:li:organization:{org_id}",
                "follower": follower_urn,
            },
        )
        if "ok" in result and result.get("result") is None:
            result["result"] = {"following": True}
        return result

    def unfollow_organization(self, follower_urn: str, organization_urn: str) -> Result:
        org_id = (
            organization_urn.split(":")[-1]
            if ":" in organization_urn
            else organization_urn
        )
        followee_urn = f"urn:li:organization:{org_id}"
        return http_request(
            "DELETE",
            f"{LINKEDIN_API_BASE}/organizationFollows/follower={_encode_urn(follower_urn)}&followee={_encode_urn(followee_urn)}",
            headers=self._headers(),
            expected=(200, 204),
            transform=lambda _d: {"unfollowed": True},
        )

    # --- Media upload ---
    def register_image_upload(self, owner_urn: str) -> Result:
        def _shape(data):
            upload_info = data.get("value", {})
            upload_mechanism = upload_info.get("uploadMechanism", {})
            media_upload = upload_mechanism.get(
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}
            )
            return {
                "upload_url": media_upload.get("uploadUrl"),
                "asset": upload_info.get("asset"),
                "full_response": data,
            }

        return http_request(
            "POST",
            f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
            headers=self._headers(),
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": owner_urn,
                    "serviceRelationships": [
                        {
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent",
                        }
                    ],
                }
            },
            transform=_shape,
        )

    def upload_image_binary(self, upload_url: str, image_data: bytes) -> Result:
        import httpx

        try:
            r = httpx.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {self._ensure_token()}",
                    "Content-Type": "application/octet-stream",
                },
                content=image_data,
                timeout=60.0,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "result": {"uploaded": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def create_post_with_uploaded_image(
        self,
        author_urn: str,
        text: str,
        asset_urn: str,
        image_title: str = "",
        visibility: str = "PUBLIC",
    ) -> Result:
        media = [
            {
                "status": "READY",
                "media": asset_urn,
                "title": {"text": image_title or ""},
            }
        ]
        return self._post_ugc(
            self._share_payload(author_urn, text, "IMAGE", media, visibility)
        )
