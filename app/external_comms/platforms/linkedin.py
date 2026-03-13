# -*- coding: utf-8 -*-
"""LinkedIn REST API v2 client — direct HTTP via httpx."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.external_comms.base import BasePlatformClient
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_OAUTH_BASE = "https://www.linkedin.com/oauth/v2"
CREDENTIAL_FILE = "linkedin.json"


@dataclass
class LinkedInCredential:
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    client_id: str = ""
    client_secret: str = ""
    linkedin_id: str = ""
    user_id: str = ""


def _encode_urn(urn: str) -> str:
    """URL-encode a LinkedIn URN for use in API paths."""
    return quote(urn, safe="")


@register_client
class LinkedInClient(BasePlatformClient):
    PLATFORM_ID = "linkedin"

    def __init__(self):
        super().__init__()
        self._cred: Optional[LinkedInCredential] = None

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> LinkedInCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, LinkedInCredential)
        if self._cred is None:
            raise RuntimeError("No LinkedIn credentials. Use /linkedin login first.")
        return self._cred

    def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
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

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a LinkedIn message. Wraps send_message_to_recipients for the base interface."""
        cred = self._load()
        sender_urn = f"urn:li:person:{cred.linkedin_id}" if cred.linkedin_id else ""
        return self.send_message_to_recipients(
            sender_urn=sender_urn,
            recipient_urns=[recipient],
            subject=kwargs.get("subject", ""),
            body=text,
        )

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def refresh_access_token(self) -> Optional[str]:
        """
        Refresh the LinkedIn OAuth access token.

        Returns:
            New access token string if successful, None otherwise.
        """
        cred = self._load()
        if not all([cred.client_id, cred.client_secret, cred.refresh_token]):
            return None

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": cred.client_id,
            "client_secret": cred.client_secret,
        }

        try:
            r = httpx.post(
                f"{LINKEDIN_OAUTH_BASE}/accessToken",
                data=payload,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                cred.access_token = data["access_token"]
                expires_in = data.get("expires_in", 5184000)  # Default 60 days
                # Subtract 24 hours as safety buffer
                cred.token_expiry = time.time() + expires_in - 86400
                save_credential(CREDENTIAL_FILE, cred)
                self._cred = cred
                return cred.access_token
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Profile operations
    # ------------------------------------------------------------------

    def get_user_profile(self) -> Dict[str, Any]:
        """
        Get the authenticated user's profile information.
        Uses /userinfo endpoint for basic profile data.
        """
        headers = {"Authorization": f"Bearer {self._ensure_token()}"}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/userinfo", headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "linkedin_id": data.get("sub"),
                        "name": data.get("name"),
                        "given_name": data.get("given_name"),
                        "family_name": data.get("family_name"),
                        "email": data.get("email"),
                        "picture": data.get("picture"),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_profile_details(self) -> Dict[str, Any]:
        """
        Get detailed profile information including headline.
        Uses the /me endpoint.
        """
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/me", headers=self._headers(), timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Connections / Network
    # ------------------------------------------------------------------

    def get_connections(self, count: int = 50, start: int = 0) -> Dict[str, Any]:
        """
        Get the authenticated user's connections.
        Note: Access to connections is limited in LinkedIn API v2.
        """
        params = {"q": "viewer", "count": min(count, 50), "start": start}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/connections", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_people(self, keywords: str, count: int = 25, start: int = 0) -> Dict[str, Any]:
        """
        Search for people on LinkedIn.
        Note: People search API may require special permissions.
        """
        params = {"q": "search", "keywords": keywords, "count": min(count, 50), "start": start}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/people", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {
                "error": f"API error: {r.status_code}",
                "details": r.text,
                "note": "People search may require specific API access.",
            }
        except Exception as e:
            return {"error": str(e)}

    def search_jobs(
        self, keywords: str, location: Optional[str] = None, count: int = 25, start: int = 0
    ) -> Dict[str, Any]:
        """
        Search for job postings on LinkedIn.
        Note: Job search API access may be limited and require special permissions.
        """
        params: Dict[str, Any] = {"keywords": keywords, "count": min(count, 50), "start": start}
        if location:
            params["locationGeoUrn"] = location
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/jobSearch", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {
                "error": f"API error: {r.status_code}",
                "details": r.text,
                "note": "LinkedIn Job Search API access may be restricted.",
            }
        except Exception as e:
            return {"error": str(e)}

    def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """Get details about a specific job posting."""
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/jobs/{job_id}", headers=self._headers(), timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def search_companies(self, keywords: str, count: int = 25, start: int = 0) -> Dict[str, Any]:
        """Search for companies/organizations on LinkedIn."""
        params = {"q": "vanityName", "vanityName": keywords}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/organizationLookup", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            # Try alternative search endpoint
            alt_params: Dict[str, Any] = {
                "q": "search",
                "keywords": keywords,
                "count": min(count, 50),
                "start": start,
            }
            alt_r = httpx.get(f"{LINKEDIN_API_BASE}/organizations", headers=self._headers(), params=alt_params, timeout=15)
            if alt_r.status_code == 200:
                return {"ok": True, "result": alt_r.json()}
            return {
                "error": f"API error: {r.status_code}",
                "details": r.text,
                "note": "Organization search may require specific API access.",
            }
        except Exception as e:
            return {"error": str(e)}

    def get_company_by_vanity_name(self, vanity_name: str) -> Dict[str, Any]:
        """
        Look up a company by its vanity name (URL slug).
        e.g. "microsoft" from linkedin.com/company/microsoft
        """
        params = {"q": "vanityName", "vanityName": vanity_name}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/organizations", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_person(self, person_id: str) -> Dict[str, Any]:
        """
        Get a person's profile by their LinkedIn ID.

        Args:
            person_id: LinkedIn person ID (numeric, not URN).
        """
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/people/(id:{person_id})", headers=self._headers(), timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Organization / Company operations
    # ------------------------------------------------------------------

    def get_my_organizations(self) -> Dict[str, Any]:
        """
        Get organizations where the authenticated user has admin access.
        Required for posting as a company page.
        """
        params = {
            "q": "roleAssignee",
            "role": "ADMINISTRATOR",
            "projection": "(elements*(organization~,roleAssignee))",
        }
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/organizationAcls", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_organization(self, organization_id: str) -> Dict[str, Any]:
        """
        Get information about a LinkedIn organization/company.

        Args:
            organization_id: Organization ID (numeric, not URN).
        """
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/organizations/{organization_id}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_organization_followers_count(self, organization_urn: str) -> Dict[str, Any]:
        """Get follower statistics for an organization."""
        org_id = organization_urn.split(":")[-1] if ":" in organization_urn else organization_urn
        params = {
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
        }
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/organizationalEntityFollowerStatistics",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Post operations
    # ------------------------------------------------------------------

    def create_text_post(
        self, author_urn: str, text: str, visibility: str = "PUBLIC"
    ) -> Dict[str, Any]:
        """
        Create a text-only post on LinkedIn.

        Args:
            author_urn: URN of author (urn:li:person:xxx or urn:li:organization:xxx).
            text: Post text content (max 3000 characters).
            visibility: "PUBLIC", "CONNECTIONS", or "LOGGED_IN".
        """
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[:3000]},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def create_article_post(
        self,
        author_urn: str,
        text: str,
        link_url: str,
        link_title: str = "",
        link_description: str = "",
        visibility: str = "PUBLIC",
    ) -> Dict[str, Any]:
        """
        Create a post with a link/article on LinkedIn.

        Args:
            author_urn: URN of author.
            text: Post text content (max 3000 characters).
            link_url: URL to share.
            link_title: Optional title for the link.
            link_description: Optional description for the link.
            visibility: "PUBLIC", "CONNECTIONS", or "LOGGED_IN".
        """
        media_item: Dict[str, Any] = {"status": "READY", "originalUrl": link_url}
        if link_title:
            media_item["title"] = {"text": link_title}
        if link_description:
            media_item["description"] = {"text": link_description}

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[:3000]},
                    "shareMediaCategory": "ARTICLE",
                    "media": [media_item],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def create_image_post(
        self,
        author_urn: str,
        text: str,
        image_url: str,
        image_title: str = "",
        visibility: str = "PUBLIC",
    ) -> Dict[str, Any]:
        """
        Create a post with an image on LinkedIn.
        Note: This version supports external image URLs.
        """
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[:3000]},
                    "shareMediaCategory": "IMAGE",
                    "media": [
                        {
                            "status": "READY",
                            "originalUrl": image_url,
                            "title": {"text": image_title or ""},
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def reshare_post(
        self,
        author_urn: str,
        original_post_urn: str,
        commentary: str = "",
        visibility: str = "PUBLIC",
    ) -> Dict[str, Any]:
        """
        Reshare/repost existing content with optional commentary.

        Args:
            author_urn: URN of the person resharing.
            original_post_urn: URN of the original post to reshare.
            commentary: Optional text to add (max 3000 chars).
            visibility: "PUBLIC", "CONNECTIONS", or "LOGGED_IN".
        """
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": commentary[:3000] if commentary else ""},
                    "shareMediaCategory": "ARTICLE",
                    "media": [
                        {
                            "status": "READY",
                            "originalUrl": f"https://www.linkedin.com/feed/update/{original_post_urn}",
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def delete_post(self, post_urn: str) -> Dict[str, Any]:
        """
        Delete a LinkedIn post.

        Args:
            post_urn: URN of the post (urn:li:share:xxx or urn:li:ugcPost:xxx).
        """
        try:
            r = httpx.delete(
                f"{LINKEDIN_API_BASE}/ugcPosts/{_encode_urn(post_urn)}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"deleted": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_post(self, post_urn: str) -> Dict[str, Any]:
        """
        Get a specific post by URN.

        Args:
            post_urn: URN of the post (urn:li:share:xxx or urn:li:ugcPost:xxx).
        """
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/ugcPosts/{_encode_urn(post_urn)}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_posts_by_author(
        self, author_urn: str, count: int = 50, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get posts authored by a specific user or organization.

        Args:
            author_urn: URN of the author (urn:li:person:xxx or urn:li:organization:xxx).
            count: Number of results (max 100).
            start: Pagination offset.
        """
        params = {
            "q": "authors",
            "authors": f"List({author_urn})",
            "count": min(count, 100),
            "start": start,
        }
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_message_to_recipients(
        self,
        sender_urn: str,
        recipient_urns: List[str],
        subject: str,
        body: str,
    ) -> Dict[str, Any]:
        """
        Send a message to one or more LinkedIn users.
        Note: Requires specific messaging permissions. Works best with InMail
        credits or for users you are already connected with.

        Args:
            sender_urn: URN of the sender (urn:li:person:xxx).
            recipient_urns: List of recipient URNs.
            subject: Message subject.
            body: Message body text.
        """
        payload = {
            "recipients": recipient_urns,
            "subject": subject,
            "body": body,
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/messages", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json() if r.text else {"sent": True}}
            return {
                "error": f"API error: {r.status_code}",
                "details": r.text,
                "note": "Messaging API requires special permissions. You may need to be connected with the recipient.",
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Connection requests / Invitations
    # ------------------------------------------------------------------

    def send_connection_request(
        self, invitee_profile_urn: str, message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a connection request (invitation) to another LinkedIn user.

        Args:
            invitee_profile_urn: URN of the person to invite (urn:li:person:xxx).
            message: Optional personalized message (max 300 characters).
        """
        payload: Dict[str, Any] = {"invitee": invitee_profile_urn}
        if message:
            payload["message"] = message[:300]
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/invitations", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json() if r.text else {"sent": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def withdraw_connection_request(self, invitation_urn: str) -> Dict[str, Any]:
        """Withdraw a pending connection request."""
        try:
            r = httpx.delete(
                f"{LINKEDIN_API_BASE}/invitations/{_encode_urn(invitation_urn)}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"withdrawn": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_sent_invitations(self, count: int = 50, start: int = 0) -> Dict[str, Any]:
        """Get sent connection invitations (pending)."""
        params = {"q": "inviter", "count": min(count, 50), "start": start}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/invitations", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_received_invitations(self, count: int = 50, start: int = 0) -> Dict[str, Any]:
        """Get received connection invitations (pending)."""
        params = {"q": "invitee", "count": min(count, 50), "start": start}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/invitations", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def respond_to_invitation(self, invitation_urn: str, action: str) -> Dict[str, Any]:
        """
        Accept or ignore a received connection invitation.

        Args:
            invitation_urn: URN of the invitation.
            action: "accept" or "ignore".
        """
        payload = {"action": action.upper()}
        try:
            r = httpx.patch(
                f"{LINKEDIN_API_BASE}/invitations/{_encode_urn(invitation_urn)}",
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"action": action, "completed": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def get_conversations(self, count: int = 20, start: int = 0) -> Dict[str, Any]:
        """
        Get message conversations.
        Note: Requires messaging permissions which may be restricted.
        """
        params = {"count": min(count, 50), "start": start}
        try:
            r = httpx.get(f"{LINKEDIN_API_BASE}/conversations", headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {
                "error": f"API error: {r.status_code}",
                "details": r.text,
                "note": "Messaging API requires special permissions.",
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Social actions (likes / reactions)
    # ------------------------------------------------------------------

    def like_post(self, actor_urn: str, post_urn: str) -> Dict[str, Any]:
        """
        Like/react to a LinkedIn post.

        Args:
            actor_urn: URN of the person liking (urn:li:person:xxx).
            post_urn: URN of the post to like.
        """
        payload = {"actor": actor_urn}
        try:
            r = httpx.post(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes",
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json() if r.text else {"liked": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def unlike_post(self, actor_urn: str, post_urn: str) -> Dict[str, Any]:
        """
        Remove like/reaction from a LinkedIn post.

        Args:
            actor_urn: URN of the person who liked.
            post_urn: URN of the post.
        """
        composite_key = quote(f"(liker:{actor_urn})", safe="")
        try:
            r = httpx.delete(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes/{composite_key}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"unliked": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_post_reactions(self, post_urn: str, count: int = 50, start: int = 0) -> Dict[str, Any]:
        """
        Get likes/reactions on a LinkedIn post.

        Args:
            post_urn: URN of the post.
            count: Number of results (max 100).
            start: Pagination offset.
        """
        params = {"count": min(count, 100), "start": start}
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/likes",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def comment_on_post(
        self,
        actor_urn: str,
        post_urn: str,
        text: str,
        parent_comment_urn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a comment on a LinkedIn post.

        Args:
            actor_urn: URN of the commenter (urn:li:person:xxx).
            post_urn: URN of the post to comment on.
            text: Comment text (max 1250 characters).
            parent_comment_urn: Optional parent comment URN for replies.
        """
        payload: Dict[str, Any] = {
            "actor": actor_urn,
            "message": {"text": text[:1250]},
        }
        if parent_comment_urn:
            payload["parentComment"] = parent_comment_urn
        try:
            r = httpx.post(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments",
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_post_comments(self, post_urn: str, count: int = 50, start: int = 0) -> Dict[str, Any]:
        """
        Get comments on a LinkedIn post.

        Args:
            post_urn: URN of the post.
            count: Number of results (max 100).
            start: Pagination offset.
        """
        params = {"count": min(count, 100), "start": start}
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def delete_comment(self, actor_urn: str, post_urn: str, comment_urn: str) -> Dict[str, Any]:
        """
        Delete a comment from a LinkedIn post.

        Args:
            actor_urn: URN of the person deleting the comment.
            post_urn: URN of the post.
            comment_urn: URN of the comment to delete.
        """
        params = {"actor": actor_urn}
        try:
            r = httpx.delete(
                f"{LINKEDIN_API_BASE}/socialActions/{_encode_urn(post_urn)}/comments/{_encode_urn(comment_urn)}",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"deleted": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_post_analytics(self, share_urns: List[str]) -> Dict[str, Any]:
        """
        Get statistics (views, likes, comments, shares) for posts.

        Args:
            share_urns: List of share/post URNs.
        """
        params = {
            "q": "organizationalEntity",
            "shares": ",".join(share_urns),
        }
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            # Try alternative endpoint for personal posts
            alt_params = {"ids": f"List({','.join(share_urns)})"}
            alt_r = httpx.get(
                f"{LINKEDIN_API_BASE}/socialMetadata",
                headers=self._headers(),
                params=alt_params,
                timeout=15,
            )
            if alt_r.status_code == 200:
                return {"ok": True, "result": alt_r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_social_metadata(self, post_urn: str) -> Dict[str, Any]:
        """
        Get social metadata (likes count, comments count, shares count) for a post.

        Args:
            post_urn: URN of the post.
        """
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/socialMetadata/{_encode_urn(post_urn)}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_organization_analytics(self, organization_urn: str) -> Dict[str, Any]:
        """
        Get page statistics/analytics for an organization.
        Requires rw_organization_admin scope.

        Args:
            organization_urn: URN or numeric ID of the organization.
        """
        org_id = organization_urn.split(":")[-1] if ":" in organization_urn else organization_urn
        params = {
            "q": "organization",
            "organization": f"urn:li:organization:{org_id}",
        }
        try:
            r = httpx.get(
                f"{LINKEDIN_API_BASE}/organizationPageStatistics",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Follow / Unfollow
    # ------------------------------------------------------------------

    def follow_organization(self, follower_urn: str, organization_urn: str) -> Dict[str, Any]:
        """
        Follow an organization/company page.

        Args:
            follower_urn: URN of the follower (urn:li:person:xxx).
            organization_urn: URN of the organization to follow.
        """
        org_id = organization_urn.split(":")[-1] if ":" in organization_urn else organization_urn
        payload = {
            "followee": f"urn:li:organization:{org_id}",
            "follower": follower_urn,
        }
        try:
            r = httpx.post(
                f"{LINKEDIN_API_BASE}/organizationFollows",
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json() if r.text else {"following": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def unfollow_organization(self, follower_urn: str, organization_urn: str) -> Dict[str, Any]:
        """
        Unfollow an organization/company page.

        Args:
            follower_urn: URN of the follower.
            organization_urn: URN of the organization to unfollow.
        """
        org_id = organization_urn.split(":")[-1] if ":" in organization_urn else organization_urn
        followee_urn = f"urn:li:organization:{org_id}"
        try:
            r = httpx.delete(
                f"{LINKEDIN_API_BASE}/organizationFollows/follower={_encode_urn(follower_urn)}&followee={_encode_urn(followee_urn)}",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code in (200, 204):
                return {"ok": True, "result": {"unfollowed": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Media upload
    # ------------------------------------------------------------------

    def register_image_upload(self, owner_urn: str) -> Dict[str, Any]:
        """
        Register an image upload to get an upload URL.
        First step in uploading images for posts.

        Args:
            owner_urn: URN of the owner (urn:li:person:xxx or urn:li:organization:xxx).
        """
        payload = {
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
        }
        try:
            r = httpx.post(
                f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                data = r.json()
                upload_info = data.get("value", {})
                upload_mechanism = upload_info.get("uploadMechanism", {})
                media_upload = upload_mechanism.get(
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}
                )
                return {
                    "ok": True,
                    "result": {
                        "upload_url": media_upload.get("uploadUrl"),
                        "asset": upload_info.get("asset"),
                        "full_response": data,
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def upload_image_binary(self, upload_url: str, image_data: bytes) -> Dict[str, Any]:
        """
        Upload image binary data to LinkedIn.
        Second step after register_image_upload.

        Args:
            upload_url: The upload URL from register_image_upload.
            image_data: Binary image data.
        """
        headers = {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/octet-stream",
        }
        try:
            r = httpx.put(upload_url, headers=headers, content=image_data, timeout=60)
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
    ) -> Dict[str, Any]:
        """
        Create a post with an uploaded image (using asset URN).

        Args:
            author_urn: URN of author.
            text: Post text.
            asset_urn: Asset URN from the upload process.
            image_title: Optional image title.
            visibility: Post visibility.
        """
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[:3000]},
                    "shareMediaCategory": "IMAGE",
                    "media": [
                        {
                            "status": "READY",
                            "media": asset_urn,
                            "title": {"text": image_title or ""},
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        try:
            r = httpx.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=self._headers(), json=payload, timeout=15)
            if r.status_code in (200, 201):
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}
