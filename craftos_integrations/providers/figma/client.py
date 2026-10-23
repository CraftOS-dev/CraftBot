"""Account-bound Figma REST client. No account files or host imports.

Reference: https://github.com/figma/rest-api-spec and INTEGRATION.md.
Only reads retry automatically. Comment writes are never replayed.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from ...base import BasePlatformClient
from ...config import ConfigStore
from ...credentials_store import load_config
from ...helpers import Result, arequest
from ...registry import register_client
from .canvas import FigmaCanvasMixin

FIGMA_API = "https://api.figma.com"
FIGMA_AUTHORIZE = "https://www.figma.com/oauth"
FIGMA_TOKEN = f"{FIGMA_API}/v1/oauth/token"
FIGMA_REFRESH = f"{FIGMA_API}/v1/oauth/refresh"
FIGMA_SCOPES = (
    "current_user:read",
    "file_content:read",
    "file_metadata:read",
    "file_versions:read",
    "file_comments:read",
    "file_comments:write",
    "library_assets:read",
    "library_content:read",
    "team_library_content:read",
    "folder_metadata:read",
)


@dataclass
class FigmaCredential:
    access_token: str = ""
    auth_kind: str = "pat"
    user_id: str = ""
    user_email: str = ""
    user_name: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0


@dataclass
class FigmaConfig:
    default_file_key: str = ""
    default_team_id: str = ""
    cache_ttl_seconds: int = 30
    max_document_nodes: int = 500


def parse_file_reference(reference: str) -> Dict[str, str]:
    """Accept a file key or official file/design/proto/board link."""
    text = str(reference or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return {"file_key": text}
    url = urlparse(text)
    if url.scheme != "https" or url.hostname not in {"figma.com", "www.figma.com"}:
        raise ValueError(
            "Use a Figma file key or an https://www.figma.com design/file/board/proto URL."
        )
    parts = url.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in {"file", "design", "proto", "board", "slides"}:
        raise ValueError("The Figma URL does not identify a file.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", parts[1]):
        raise ValueError("Invalid Figma file key.")
    result = {"file_key": parts[1]}
    node = parse_qs(url.query).get("node-id", [""])[0]
    if node:
        result["node_id"] = normalize_node_id(node)
    return result


def normalize_node_id(value: str) -> str:
    text = unquote(str(value or "")).strip()
    # URL links use 12-34; the REST API uses 12:34. Some ids have I… prefixes.
    text = re.sub(r"(?<=\d)-(?=\d)", ":", text)
    if not re.fullmatch(r"[A-Za-z0-9_:;.]+", text):
        raise ValueError("Invalid node id; use the id from a Figma node or node URL.")
    return text


def _segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("A resource identifier is required.")
    return quote(text, safe="")


def _ids(values: Any) -> list[str]:
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("Provide one or more node ids (or a node URL).")
    if len(values) > 100:
        raise ValueError("At most 100 node ids may be requested at once.")
    return [normalize_node_id(v) for v in values]


@register_client
class FigmaClient(FigmaCanvasMixin, BasePlatformClient):
    PLATFORM_ID = "figma"

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[FigmaCredential] = None
        self._persist = None
        self._cache: Dict[str, Any] = {}
        self._refresh_lock = asyncio.Lock()

    def bind_credential(self, credential: Dict[str, Any], persist) -> None:
        known = FigmaCredential.__dataclass_fields__
        self._cred = FigmaCredential(
            **{k: v for k, v in credential.items() if k in known}
        )
        self._persist = persist
        self._cache.clear()

    def _load(self) -> FigmaCredential:
        if self._cred is None:
            raise RuntimeError("Figma client used before credential binding.")
        return self._cred

    def _config(self) -> FigmaConfig:
        return load_config("figma_config.json", FigmaConfig) or FigmaConfig()

    def has_credentials(self) -> bool:
        return self._cred is not None and bool(self._cred.access_token)

    async def connect(self) -> None:
        self._connected = self.has_credentials()

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return await self.post_comment(recipient, text, **kwargs)

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        if cred.auth_kind == "oauth":
            return {"Authorization": f"Bearer {cred.access_token}"}
        return {"X-Figma-Token": cred.access_token}

    async def refresh_access_token(self, *, force: bool = False) -> Result:
        async with self._refresh_lock:
            cred = self._load()
            if cred.auth_kind != "oauth":
                return {"ok": True, "result": {}}
            if not force and (
                not cred.token_expiry or cred.token_expiry > time.time() + 60
            ):
                return {"ok": True, "result": {}}
            client_id = ConfigStore.get_oauth("FIGMA_CLIENT_ID")
            client_secret = ConfigStore.get_oauth("FIGMA_CLIENT_SECRET")
            if not client_id or not client_secret or not cred.refresh_token:
                return {
                    "error": "Figma OAuth refresh is unavailable. Configure FIGMA_CLIENT_ID/FIGMA_CLIENT_SECRET and reconnect."
                }
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            result = await arequest(
                "POST",
                FIGMA_REFRESH,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"refresh_token": cred.refresh_token},
                expected=(200,),
            )
            if "error" in result:
                return {"error": "Figma OAuth refresh failed. Reconnect the account."}
            tokens = result.get("result") or {}
            if not tokens.get("access_token"):
                return {
                    "error": "Figma OAuth refresh returned no access token. Reconnect the account."
                }
            updated = asdict(cred)
            updated["access_token"] = tokens["access_token"]
            updated["token_expiry"] = time.time() + float(tokens.get("expires_in") or 0)
            if tokens.get("refresh_token"):
                updated["refresh_token"] = tokens["refresh_token"]
            # Persist before making the refreshed token visible to concurrent calls.
            self._persist(updated)
            self._cred = FigmaCredential(**updated)
            self._cache.clear()
            return {"ok": True, "result": {}}

    async def _request(
        self, method: str, path: str, *, params=None, json_body=None, cache=True
    ) -> Result:
        refreshed = await self.refresh_access_token()
        if "error" in refreshed:
            return refreshed
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key = path + json.dumps(params, sort_keys=True)
        ttl = min(max(int(self._config().cache_ttl_seconds), 0), 300)
        if method == "GET" and cache and ttl and key in self._cache:
            deadline, value = self._cache[key]
            if deadline > time.monotonic():
                return copy.deepcopy(value)
        metadata: Dict[str, Any] = {}

        def capture(response):
            metadata["status"] = response.status_code
            metadata["retry_after"] = response.headers.get("Retry-After")

        for attempt in range(3):
            metadata.clear()
            result = await arequest(
                method,
                FIGMA_API + path,
                headers=self._headers(),
                params=params,
                json=json_body,
                expected=(200, 201, 204),
                response_hook=capture,
            )
            if "error" not in result:
                if method != "GET":
                    self._cache.clear()
                elif cache and ttl:
                    # Bound memory as well as age; entries never span accounts.
                    if len(self._cache) >= 64:
                        self._cache.clear()
                    self._cache[key] = (time.monotonic() + ttl, copy.deepcopy(result))
                return result
            status = metadata.get("status")
            if status == 429:
                try:
                    delay = max(float(metadata.get("retry_after") or 1), 0)
                except (ValueError, TypeError):
                    delay = 1
                if method == "GET" and attempt < 2 and delay <= 5:
                    await asyncio.sleep(delay)
                    continue
                return {
                    "error": f"Figma rate limit reached. Retry after {delay:g} seconds; limits depend on seat and file plan.",
                    "details": {"retry_after": delay},
                }
            if status in (401, 403):
                return {
                    "error": "Figma denied access: the token may be expired, missing a required scope, or lack access to this resource. Check permissions or reconnect.",
                    "details": {"status": status},
                }
            if status == 404:
                return {
                    "error": "Figma resource not found or inaccessible. Check the file key/resource id and account access."
                }
            return result
        return {"error": "Figma request failed."}

    def _file(self, file_key: str = "") -> Dict[str, str]:
        return parse_file_reference(file_key or self._config().default_file_key)

    def _file_path(self, file_key: str, suffix: str = "") -> str:
        return f"/v1/files/{_segment(self._file(file_key)['file_key'])}{suffix}"

    def _nodes(self, file_key: str, node_ids: Any) -> list[str]:
        ref = self._file(file_key)
        return _ids(node_ids or ([ref["node_id"]] if ref.get("node_id") else []))

    def _bound_document(self, result: Result) -> Result:
        if "error" in result:
            return result
        body = copy.deepcopy(result["result"])
        cap = min(max(int(self._config().max_document_nodes), 1), 2000)
        count = 0
        truncated = False

        def visit(node):
            nonlocal count, truncated
            count += 1
            children = node.get("children") or []
            kept = []
            for child in children:
                if count >= cap:
                    truncated = True
                    break
                visit(child)
                kept.append(child)
            if len(kept) < len(children):
                node["children_truncated"] = True
            if "children" in node:
                node["children"] = kept

        if isinstance(body, dict):
            if isinstance(body.get("document"), dict):
                visit(body["document"])
            elif isinstance(body.get("nodes"), dict):
                kept_nodes = {}
                for node_id, entry in body["nodes"].items():
                    if entry is None:
                        kept_nodes[node_id] = None
                    elif count < cap:
                        visit(entry["document"])
                        kept_nodes[node_id] = entry
                    else:
                        truncated = True
                body["nodes"] = kept_nodes
            body["returned_nodes"] = count
            body["truncated"] = truncated
        return {"ok": True, "result": body}

    @staticmethod
    def _local_page(
        result: Result, field: str, limit: int = 30, offset: int = 0
    ) -> Result:
        """Endpoints without server paging return a documented local slice."""
        if "error" in result:
            return result
        body = copy.deepcopy(result["result"])
        container = body.get("meta", body)
        rows = container.get(field, [])
        limit = min(max(int(limit), 1), 100)
        offset = max(int(offset), 0)
        container[field] = rows[offset : offset + limit]
        body["pagination"] = {
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "local": True,
        }
        return {"ok": True, "result": body}

    async def get_current_user(self) -> Result:
        return await self._request("GET", "/v1/me")

    async def parse_url(self, file_key: str) -> Result:
        return {"ok": True, "result": parse_file_reference(file_key)}

    async def get_file(
        self, file_key: str = "", depth: int = 2, version: str = ""
    ) -> Result:
        if not 1 <= int(depth) <= 10:
            raise ValueError("depth must be between 1 and 10.")
        result = await self._request(
            "GET",
            self._file_path(file_key),
            params={"depth": depth, "version": version, "branch_data": "true"},
        )
        return self._bound_document(result)

    async def get_file_metadata(self, file_key: str = "") -> Result:
        return await self._request("GET", self._file_path(file_key, "/meta"))

    async def get_nodes(
        self,
        file_key: str = "",
        node_ids: Any = None,
        depth: int = 2,
        version: str = "",
    ) -> Result:
        if not 1 <= int(depth) <= 10:
            raise ValueError("depth must be between 1 and 10.")
        result = await self._request(
            "GET",
            self._file_path(file_key, "/nodes"),
            params={
                "ids": ",".join(self._nodes(file_key, node_ids)),
                "depth": depth,
                "version": version,
            },
        )
        return self._bound_document(result)

    async def find_nodes(
        self,
        file_key: str = "",
        name: str = "",
        node_type: str = "",
        depth: int = 4,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        """Search the fetched, bounded tree; never imply a global file search."""
        if not name and not node_type:
            raise ValueError("Provide a node name or type to search for.")
        result = await self.get_file(file_key, depth)
        if "error" in result:
            return result
        body = result["result"]
        stack = [body.get("document", {})]
        matches = []
        while stack:
            node = stack.pop()
            if name.lower() in node.get("name", "").lower() and (
                not node_type or node.get("type") == node_type.upper()
            ):
                matches.append(
                    {
                        k: node[k]
                        for k in ("id", "name", "type", "absoluteBoundingBox")
                        if k in node
                    }
                )
            stack.extend(reversed(node.get("children", [])))
        result = self._local_page(
            {"ok": True, "result": {"nodes": matches}}, "nodes", limit, offset
        )
        result["result"].update(
            {
                "search_scope": "fetched_tree",
                "document_truncated": body.get("truncated", False),
                "searched_depth": depth,
            }
        )
        return result

    async def list_versions(
        self, file_key: str = "", limit: int = 30, before: str = "", after: str = ""
    ) -> Result:
        path = self._file_path(file_key, "/versions")
        params = {
            "page_size": min(max(int(limit), 1), 100),
            "before": before,
            "after": after,
        }
        for cursor in (before, after):
            if "://" not in cursor and not cursor.startswith("//"):
                continue
            url = urlparse(cursor)
            if (
                url.scheme != "https"
                or url.hostname != "api.figma.com"
                or url.port not in (None, 443)
                or url.username
                or url.password
                or url.path != path
                or (before and after)
            ):
                raise ValueError(
                    "Use one pagination URL returned for this Figma file's version history."
                )
            # Native pagination returns URLs with secondary cursors, rather
            # than a single opaque value. Never navigate to a supplied URL.
            query = parse_qs(url.query)
            params = {
                key: values[0]
                for key, values in query.items()
                if key
                in {
                    "before",
                    "after",
                    "secondary_before",
                    "secondary_after",
                    "column",
                    "secondary_column",
                }
            }
            if not params.get("before") and not params.get("after"):
                raise ValueError("The version pagination URL has no cursor.")
            params["page_size"] = min(max(int(limit), 1), 100)
        return await self._request(
            "GET",
            path,
            params=params,
        )

    async def export_images(
        self,
        file_key: str = "",
        node_ids: Any = None,
        format: str = "png",
        scale: float = 1,
        version: str = "",
    ) -> Result:
        if format not in {"png", "jpg", "svg", "pdf"}:
            raise ValueError("format must be png, jpg, svg or pdf.")
        if not 0.01 <= float(scale) <= 4:
            raise ValueError("scale must be between 0.01 and 4.")
        ids = self._nodes(file_key, node_ids)
        result = await self._request(
            "GET",
            f"/v1/images/{_segment(self._file(file_key)['file_key'])}",
            params={
                "ids": ",".join(ids),
                "format": format,
                "scale": scale,
                "version": version,
            },
        )
        if "error" not in result:
            body = result["result"]
            if body.get("err"):
                return {"error": str(body["err"])}
            body["failed_node_ids"] = [
                i for i in ids if not body.get("images", {}).get(i)
            ]
            body["temporary_urls"] = True
        return result

    async def get_image_fills(self, file_key: str = "") -> Result:
        return await self._request("GET", self._file_path(file_key, "/images"))

    async def download_images(
        self,
        file_key: str,
        output_dir: str,
        node_ids: Any = None,
        format: str = "png",
        scale: float = 1,
        version: str = "",
    ) -> Result:
        directory = Path(output_dir).expanduser()
        if not directory.is_absolute():
            raise ValueError("output_dir must be an absolute local directory.")
        result = await self.export_images(file_key, node_ids, format, scale, version)
        if "error" in result:
            return result
        file_id = self._file(file_key)["file_key"]

        def save():
            directory.mkdir(parents=True, exist_ok=True)
            paths, failures = {}, list(result["result"]["failed_node_ids"])
            for node_id, url in result["result"].get("images", {}).items():
                if not url:
                    continue
                parsed = urlparse(url)
                host = parsed.hostname or ""
                if parsed.scheme != "https" or not (
                    host.endswith(".figma.com") or host.endswith(".amazonaws.com")
                ):
                    failures.append(node_id)
                    continue
                # No bearer token reaches asset hosts. Unique names prevent overwrites.
                temp_path = None
                try:
                    normalize_node_id(node_id)
                    with httpx.stream(
                        "GET", url, timeout=30, follow_redirects=False
                    ) as response:
                        response.raise_for_status()
                        with tempfile.NamedTemporaryFile(
                            prefix=f"figma-{file_id}-{node_id.replace(':', '-')}-",
                            suffix=f".{format}",
                            dir=directory,
                            delete=False,
                        ) as output:
                            temp_path = Path(output.name)
                            size = 0
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 50 * 1024 * 1024:
                                    raise ValueError(
                                        "Export exceeds 50 MiB download limit."
                                    )
                                output.write(chunk)
                        paths[node_id] = str(temp_path)
                except Exception:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                    failures.append(node_id)
            if not paths:
                return {
                    "error": "No Figma images could be downloaded.",
                    "details": {"failed_node_ids": failures},
                }
            return {"ok": True, "result": {"files": paths, "failed_node_ids": failures}}

        return await asyncio.to_thread(save)

    async def list_comments(
        self, file_key: str = "", limit: int = 30, offset: int = 0
    ) -> Result:
        result = await self._request(
            "GET", self._file_path(file_key, "/comments"), params={"as_md": "true"}
        )
        return self._local_page(result, "comments", limit, offset)

    async def post_comment(
        self,
        file_key: str,
        message: str,
        comment_id: str = "",
        client_meta: Optional[dict] = None,
    ) -> Result:
        if not str(message).strip():
            raise ValueError("A non-empty comment message is required.")
        payload: Dict[str, Any] = {"message": message}
        if comment_id:
            payload["comment_id"] = comment_id
        if client_meta is not None:
            payload["client_meta"] = client_meta
        return await self._request(
            "POST", self._file_path(file_key, "/comments"), json_body=payload
        )

    async def delete_comment(self, file_key: str, comment_id: str) -> Result:
        return await self._request(
            "DELETE", self._file_path(file_key, f"/comments/{_segment(comment_id)}")
        )

    async def reply_comment(
        self, file_key: str, comment_id: str, message: str
    ) -> Result:
        if not str(comment_id).strip():
            raise ValueError("A root comment id is required for a reply.")
        return await self.post_comment(file_key, message, comment_id=comment_id)

    async def list_comment_reactions(
        self, file_key: str, comment_id: str, cursor: str = ""
    ) -> Result:
        return await self._request(
            "GET",
            self._file_path(file_key, f"/comments/{_segment(comment_id)}/reactions"),
            params={"cursor": cursor},
        )

    async def add_comment_reaction(
        self, file_key: str, comment_id: str, emoji: str
    ) -> Result:
        return await self._request(
            "POST",
            self._file_path(file_key, f"/comments/{_segment(comment_id)}/reactions"),
            json_body={"emoji": emoji},
        )

    async def delete_comment_reaction(
        self, file_key: str, comment_id: str, emoji: str
    ) -> Result:
        return await self._request(
            "DELETE",
            self._file_path(file_key, f"/comments/{_segment(comment_id)}/reactions"),
            params={"emoji": emoji},
        )

    def _team(self, team_id: str) -> str:
        value = str(team_id or self._config().default_team_id).strip()
        if value.startswith("https://"):
            parsed = urlparse(value)
            if parsed.hostname not in {"figma.com", "www.figma.com"}:
                raise ValueError("Use an official Figma team URL.")
            match = re.search(r"/team/(\d+)(?:/|$)", parsed.path)
            if not match:
                raise ValueError("The URL does not contain a team id.")
            value = match.group(1)
        if not value.isdigit():
            raise ValueError(
                "Supply a numeric team id or Figma team URL; team ids cannot be discovered through the API."
            )
        return value

    async def list_team_folders(
        self, team_id: str = "", limit: int = 30, offset: int = 0
    ) -> Result:
        result = await self._request("GET", f"/v2/teams/{self._team(team_id)}/folders")
        return self._local_page(result, "folders", limit, offset)

    async def list_subfolders(
        self, folder_id: str, limit: int = 30, offset: int = 0
    ) -> Result:
        return self._local_page(
            await self._request("GET", f"/v2/folders/{_segment(folder_id)}/folders"),
            "folders",
            limit,
            offset,
        )

    async def list_folder_files(
        self, folder_id: str, limit: int = 30, offset: int = 0
    ) -> Result:
        return self._local_page(
            await self._request("GET", f"/v2/folders/{_segment(folder_id)}/files"),
            "files",
            limit,
            offset,
        )

    async def get_folder_metadata(self, folder_id: str) -> Result:
        segment = _segment(folder_id)
        result = await self._request("GET", f"/v2/folders/{segment}/meta")
        if self._load().auth_kind == "pat" and result.get("details", {}).get(
            "status"
        ) in (401, 403):
            # The PAT settings UI does not offer folder_metadata:read. Its
            # folders:read endpoint still verifies access and supplies the name.
            listing = await self._request("GET", f"/v2/folders/{segment}/folders")
            if "error" in listing:
                return result
            return {
                "ok": True,
                "result": {
                    "id": str(folder_id).strip(),
                    "name": listing["result"]["name"],
                    "partial_metadata": True,
                    "source": "folder_listing",
                    "unavailable_fields": [
                        "thumbnail_url",
                        "file_count",
                        "updated_at",
                        "created_at",
                    ],
                },
            }
        return result

    async def _team_library(
        self, team_id: str, resource: str, limit: int, after: str, before: str
    ) -> Result:
        return await self._request(
            "GET",
            f"/v1/teams/{self._team(team_id)}/{resource}",
            params={
                "page_size": min(max(int(limit), 1), 100),
                "after": after,
                "before": before,
            },
        )

    async def _file_library(
        self, file_key: str, resource: str, limit: int, offset: int
    ) -> Result:
        return self._local_page(
            await self._request("GET", self._file_path(file_key, f"/{resource}")),
            resource,
            limit,
            offset,
        )

    async def list_team_components(
        self, team_id: str = "", limit: int = 30, after: str = "", before: str = ""
    ) -> Result:
        return await self._team_library(team_id, "components", limit, after, before)

    async def list_file_components(
        self, file_key: str = "", limit: int = 30, offset: int = 0
    ) -> Result:
        return await self._file_library(file_key, "components", limit, offset)

    async def get_component(self, component_key: str) -> Result:
        return await self._request("GET", f"/v1/components/{_segment(component_key)}")

    async def list_team_component_sets(
        self, team_id: str = "", limit: int = 30, after: str = "", before: str = ""
    ) -> Result:
        return await self._team_library(team_id, "component_sets", limit, after, before)

    async def list_file_component_sets(
        self, file_key: str = "", limit: int = 30, offset: int = 0
    ) -> Result:
        return await self._file_library(file_key, "component_sets", limit, offset)

    async def get_component_set(self, component_set_key: str) -> Result:
        return await self._request(
            "GET", f"/v1/component_sets/{_segment(component_set_key)}"
        )

    async def list_team_styles(
        self, team_id: str = "", limit: int = 30, after: str = "", before: str = ""
    ) -> Result:
        return await self._team_library(team_id, "styles", limit, after, before)

    async def list_file_styles(
        self, file_key: str = "", limit: int = 30, offset: int = 0
    ) -> Result:
        return await self._file_library(file_key, "styles", limit, offset)

    async def get_style(self, style_key: str) -> Result:
        return await self._request("GET", f"/v1/styles/{_segment(style_key)}")
