"""Host-only, resumable source migration. Never import this into a consumer.

Destination writes precede the single source commit. The host storage adapter
must compare the source revision and atomically publish the reference document;
failure leaves the old source intact and retries reuse the same destination IDs.
No plaintext rollback file or raw-secret-returning resolver is produced here.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from uuid import uuid5

from .catalog import model_helpers
from .contracts import CredentialKind
from .errors import VaultError, VaultErrorCode as Code, sanitized_errors
from .identity import _label
from .references import SourceReference, is_reference
from .secrets import Secret
from .records import origins as validate_origins, validate_fields
from .vault import SourceImport


@dataclass(frozen=True)
class MigrationResult:
    imported: int
    retained_references: int
    review_required: int = 0
    retained_derived: int = 0


def classify_integration(provider: str, credential: dict) -> str:
    """Provider/provenance classification; never guess from a 'token' key."""
    if "source_reference" in credential:
        return "reference"
    if provider == "figma":
        return {"pat": "source", "oauth": "derived"}.get(
            credential.get("auth_kind"), "review_required"
        )
    if provider == "github":
        return "source"  # This repository's GitHub provider is PAT-only.
    if provider in {"stripe", "posthog", "telegram_bot", "line"}:
        return "source"
    if provider == "discord":
        return "source" if credential.get("bot_token") else "derived"
    if provider in {"supabase", "hubspot"}:
        return {"pat": "source", "private_app": "source", "oauth": "derived"}.get(
            credential.get("auth_kind"), "review_required"
        )
    if provider in {
        "gmail",
        "google_calendar",
        "google_docs",
        "google_drive",
        "google_youtube",
        "outlook",
        "whatsapp_web",
        "telegram_user",
    }:
        return "derived"
    # OAuth-generated Slack bot credentials and manually entered Slack bot
    # credentials can share the same fields. Missing provenance requires review.
    return "review_required"


@sanitized_errors
def migrate_model_document(
    vault, source_id: str, document: Secret, commit, *, helper_catalog=None
):
    """Trusted compare-and-swap adapter receives the new Secret document only.

    This callable is host-internal, never a registered helper or a consumer
    callback. Unknown providers, malformed pools and static AWS credentials
    abort before any source retirement; token/session sections are untouched.
    """
    _label(source_id)
    if not isinstance(document, Secret) or type(document.reveal()) is not dict:
        raise VaultError(Code.INVALID)
    candidate = Secret(copy.deepcopy(document.reveal()))
    aws = candidate.reveal().get("aws_credentials", {})
    if type(aws) is not dict:
        raise VaultError(Code.INVALID)
    origins = {}
    aws_origins = set()
    from urllib.parse import urlsplit

    for helper in model_helpers() if helper_catalog is None else helper_catalog:
        if not helper["helper"].startswith("model_"):
            continue
        provider = helper["helper"][len("model_") :]
        endpoint = urlsplit(helper["endpoint"])
        if helper.get("protocol") == "aws_bedrock":
            aws_origins.add(f"https://{endpoint.netloc}")
        origins.setdefault("google" if provider == "gemini" else provider, set()).add(
            f"https://{endpoint.netloc}"
        )
    jobs, retained = [], 0
    for block, pool in (("api_keys", False), ("extra_api_keys", True)):
        entries = candidate.reveal().get(block, {})
        if type(entries) is not dict:
            raise VaultError(Code.INVALID)
        for provider, values in entries.items():
            if not isinstance(provider, str):
                raise VaultError(Code.INVALID)
            if pool and type(values) is not list:
                raise VaultError(Code.INVALID)
            for index, value in enumerate(values if pool else [values]):
                if not isinstance(value, str):
                    raise VaultError(Code.INVALID)
                if not value:
                    continue
                if is_reference(value):
                    retained += 1
                    continue
                if provider not in origins:
                    raise VaultError(Code.INVALID)
                locator = f"{block}/{provider}/{index}"
                jobs.append(
                    (
                        block,
                        provider,
                        index,
                        Secret(value),
                        locator,
                        tuple(sorted(origins[provider])),
                    )
                )
    imports = list(
        SourceImport(
            uuid5(vault.profile.scope.profile_id, source_id + "/" + locator),
            CredentialKind.API_KEY,
            provider,
            "Primary" if block == "api_keys" else f"Pool {index + 1}",
            Secret({"api_key": value.reveal()}),
            allowed,
        )
        for block, provider, index, value, locator, allowed in jobs
    )
    aws_import = False
    if aws.get("source_reference"):
        if not is_reference(aws["source_reference"]):
            raise VaultError(Code.INVALID)
        retained += 1
    if (aws.get("access_key_id") or aws.get("secret_access_key")) and not aws.get(
        "session_token"
    ):
        if aws.get("source_reference"):
            raise VaultError(Code.CONFLICT)
        region = (
            candidate.reveal().get("endpoints", {}).get("aws_region") or "us-east-1"
        )
        origin = f"https://bedrock-runtime.{region}.amazonaws.com"
        if origin not in aws_origins:
            raise VaultError(Code.INVALID)
        fields = Secret(
            {key: aws.get(key) for key in ("access_key_id", "secret_access_key")}
        )
        validate_fields(CredentialKind.SERVICE_SECRET, fields)
        imports.append(
            SourceImport(
                uuid5(vault.profile.scope.profile_id, source_id + "/aws/static"),
                CredentialKind.SERVICE_SECRET,
                "AWS Bedrock",
                "Static AWS account",
                fields,
                (origin,),
            )
        )
        aws_import = True
    imported = vault.import_sources(tuple(imports)) if imports else ()
    for (block, provider, index, value, locator, allowed), item in zip(
        jobs, imported[: len(jobs)]
    ):
        ref = item.summary.reference
        encoded = SourceReference(
            ref.scope.profile_id, ref.credential_id, ref.version
        ).encode()
        if block == "api_keys":
            candidate.reveal()[block][provider] = encoded
        else:
            candidate.reveal()[block][provider][index] = encoded
    if aws_import:
        ref = imported[-1].summary.reference
        aws["source_reference"] = SourceReference(
            ref.scope.profile_id, ref.credential_id, ref.version
        ).encode()
        aws["auth_mode"] = "vault"
        del aws["access_key_id"], aws["secret_access_key"]
    # One commit, after every destination has been read back successfully.
    # Existing generated-token/session values remain exactly equal by deep copy.
    commit(candidate)
    return MigrationResult(len(imports), retained)


@sanitized_errors
def migrate_browser_document(vault, source_id: str, document: Secret):
    """Strict legacy login conversion. Returns an ID map, never login fields."""
    _label(source_id)
    value = document.reveal()
    if (
        type(value) is not dict
        or type(value.get("version")) is not int
        or value["version"] != 1
        or set(value) != {"version", "entries"}
        or type(value["entries"]) is not list
        or len(value["entries"]) > 5000
    ):
        raise VaultError(Code.INVALID)
    jobs, seen = [], set()
    allowed = {
        "id",
        "site",
        "username",
        "password",
        "label",
        "createdAt",
        "updatedAt",
        "lastUsedAt",
    }
    for entry in map(Secret, value["entries"]):
        item = entry.reveal()
        if (
            type(item) is not dict
            or set(item) - allowed
            or not {"id", "site", "username", "password"} <= set(item)
        ):
            raise VaultError(Code.INVALID)
        old_id, site = item["id"], item["site"]
        if (
            not isinstance(old_id, str)
            or not 1 <= len(old_id) <= 64
            or old_id in seen
            or not isinstance(site, str)
        ):
            raise VaultError(Code.INVALID)
        seen.add(old_id)
        origin = validate_origins(
            (site if site.startswith("https://") else "https://" + site,)
        )
        fields = Secret({"username": item["username"], "password": item["password"]})
        validate_fields(CredentialKind.LOGIN, fields)
        label = item.get("label") or "Imported login " + old_id[:8]
        _label(label)
        jobs.append((old_id, origin, fields, label))
    mapping = {}
    imported = (
        vault.import_sources(
            tuple(
                SourceImport(
                    uuid5(
                        vault.profile.scope.profile_id, source_id + "/browser/" + old_id
                    ),
                    CredentialKind.LOGIN,
                    "Browser login",
                    label,
                    fields,
                    origin,
                )
                for old_id, origin, fields, label in jobs
            )
        )
        if jobs
        else ()
    )
    for (old_id, origin, fields, label), details in zip(jobs, imported):
        ref = details.summary.reference
        mapping[old_id] = SourceReference(
            ref.scope.profile_id, ref.credential_id, ref.version
        ).encode()
    return mapping


SOURCE_FIELDS = {
    "twitter": ("api_secret", ()),
    **{p: (None, ()) for p in ("lark", "lark_drive", "lark_calendar", "telegram_user")},
    "github": ("access_token", ()),
    "figma": ("access_token", ()),
    "slack": ("bot_token", ()),
    "discord": ("bot_token", ()),
    "stripe": ("api_key", ()),
    "notion": ("token", ()),
    "hubspot": ("access_token", ()),
    "posthog": ("api_key", ()),
    "supabase": ("access_token", ()),
    "line": ("channel_access_token", ("channel_secret",)),
    "telegram_bot": ("bot_token", ()),
    "whatsapp_business": ("access_token", ("app_secret", "verify_token")),
    "jira": ("api_token", ()),
    **{
        p: (None, ())
        for p in (
            "gmail",
            "google_drive",
            "google_calendar",
            "google_docs",
            "google_youtube",
            "linkedin",
            "outlook",
        )
    },
}

OAUTH_PROVIDERS = {
    **{
        p: "google"
        for p in (
            "gmail",
            "google_drive",
            "google_calendar",
            "google_docs",
            "google_youtube",
        )
    },
    **{p: p for p in ("slack", "linkedin", "hubspot", "figma", "notion", "supabase")},
}


@sanitized_errors
def migrate_integration_document(
    vault,
    source_id,
    provider,
    document,
    commit,
    *,
    source_accounts=(),
    helper_catalog=None,
):
    """Retire only classified manual sources; preserve generated records verbatim.

    Ambiguous legacy modes require explicit account IDs at the native owner
    action. An OAuth mode or refresh token can never be overridden by that list.
    Account identities, primary, aliases, timestamps and session data are copied.
    """
    from .catalog import integration_helpers
    from urllib.parse import urlsplit

    _label(source_id)
    if provider not in SOURCE_FIELDS or not isinstance(document, Secret):
        raise VaultError(Code.INVALID)
    candidate = Secret(copy.deepcopy(document.reveal()))
    value = candidate.reveal()
    if (
        type(value) is not dict
        or type(value.get("version")) is not int
        or value["version"] != 2
        or type(value.get("accounts")) is not dict
        or len(value["accounts"]) > 5000
    ):
        raise VaultError(Code.INVALID)
    selected = set(source_accounts)
    if selected - set(value["accounts"]):
        raise VaultError(Code.INVALID)
    catalog = integration_helpers() if helper_catalog is None else helper_catalog
    allowed = tuple(
        sorted(
            {
                f"https://{urlsplit(r['endpoint']).netloc}"
                for r in (catalog)
                if r["helper"] == "integration_" + provider
            }
        )
    )
    if not allowed and SOURCE_FIELDS[provider][0] is not None:
        raise VaultError(Code.INVALID)
    jobs, bindings, retained = [], [], 0
    review_required, retained_derived = 0, 0
    primary, auxiliary = SOURCE_FIELDS[provider]
    for identity, record in value["accounts"].items():
        _label(identity)
        if type(record) is not dict or type(record.get("credential")) is not dict:
            raise VaultError(Code.INVALID)
        credential = Secret(record["credential"])
        data = credential.reveal()
        if provider in (
            "lark",
            "lark_drive",
            "lark_calendar",
            "telegram_user",
            "twitter",
        ):
            source_name = (
                "api_hash"
                if provider == "telegram_user"
                else "api_secret"
                if provider == "twitter"
                else "app_secret"
            )
            source = data.get(source_name)
            if not source:
                if provider == "twitter" and is_reference(data.get("source_reference")):
                    retained += 1
                    continue
                retained_derived += 1
                continue
            if is_reference(source):
                retained += 1
                continue
            helper = (
                "auth_telegram_user"
                if provider == "telegram_user"
                else "integration_twitter"
                if provider == "twitter"
                else "auth_lark"
            )
            special_origins = tuple(
                sorted(
                    {
                        f"https://{urlsplit(r['endpoint']).netloc}"
                        for r in catalog
                        if r["helper"] == helper
                    }
                )
            )
            if not special_origins:
                raise VaultError(Code.INVALID)
            kind = (
                CredentialKind.SERVICE_SECRET
                if provider in ("telegram_user", "twitter")
                else CredentialKind.API_KEY
            )
            secret = Secret(
                {"api_key": data.get("api_key"), "api_secret": source}
                if provider == "twitter"
                else {"api_hash": source}
                if provider == "telegram_user"
                else {"api_key": source}
            )
            validate_fields(kind, secret)
            jobs.append(
                SourceImport(
                    uuid5(
                        vault.profile.scope.profile_id,
                        source_id + "/" + provider + "/" + identity + "/" + source_name,
                    ),
                    kind,
                    provider,
                    identity + " app",
                    secret,
                    special_origins,
                )
            )
            bindings.append((data, source_name, provider == "twitter"))
            continue  # Generated tokens, expiry and sessions remain byte-for-byte values.
        oauth_secret = data.get("client_secret")
        if oauth_secret and provider in OAUTH_PROVIDERS:
            if is_reference(oauth_secret):
                retained += 1
            else:
                oauth_allowed = tuple(
                    sorted(
                        {
                            f"https://{urlsplit(r['endpoint']).netloc}"
                            for r in catalog
                            if r["helper"] == "oauth_" + OAUTH_PROVIDERS[provider]
                        }
                    )
                )
                if not oauth_allowed:
                    raise VaultError(Code.INVALID)
                jobs.append(
                    SourceImport(
                        uuid5(
                            vault.profile.scope.profile_id,
                            source_id
                            + "/"
                            + provider
                            + "/"
                            + identity
                            + "/client_secret",
                        ),
                        CredentialKind.API_KEY,
                        provider,
                        identity + " OAuth client",
                        Secret({"api_key": oauth_secret}),
                        oauth_allowed,
                    )
                )
                bindings.append((data, "client_secret", False))
        if primary is None:
            retained_derived += 1
            continue
        if data.get("source_reference"):
            if not is_reference(data["source_reference"]):
                raise VaultError(Code.INVALID)
            retained += 1
            continue
        mode = classify_integration(provider, data)
        if data.get("auth_kind") == "oauth" or data.get("refresh_token"):
            if identity in selected:
                raise VaultError(Code.INVALID)
            retained_derived += 1
            continue
        if mode == "review_required" and identity not in selected:
            # Retain unknown provenance; report it without echoing values.
            review_required += 1
            continue
        if mode == "derived":
            retained_derived += 1
            continue
        if not data.get(primary):
            raise VaultError(Code.INVALID)
        if provider in ("jira", "posthog"):
            host = (
                data.get("domain")
                if provider == "jira"
                else data.get("host", "https://us.posthog.com")
            )
            if not isinstance(host, str) or not host:
                raise VaultError(Code.INVALID)
            origin = host if host.startswith("https://") else "https://" + host
            origin = origin.rstrip("/")
            if (
                validate_origins((origin,)) != (origin,)
                or origin not in allowed
                or origin.endswith(".invalid")
            ):
                raise VaultError(Code.INVALID)
        fields = [(primary, CredentialKind.API_KEY, Secret({"api_key": data[primary]}))]
        if provider == "jira":
            fields = [
                (
                    primary,
                    CredentialKind.SERVICE_SECRET,
                    Secret({"api_token": data[primary], "username": data.get("email")}),
                )
            ]
        fields.extend(
            (name, CredentialKind.API_KEY, Secret({"api_key": data[name]}))
            for name in auxiliary
            if data.get(name)
        )
        for name, kind, secret in fields:
            validate_fields(kind, secret)
            jobs.append(
                SourceImport(
                    uuid5(
                        vault.profile.scope.profile_id,
                        source_id + "/" + provider + "/" + identity + "/" + name,
                    ),
                    kind,
                    provider,
                    identity if name == primary else identity + " " + name,
                    secret,
                    allowed,
                )
            )
            bindings.append((data, name, name == primary))
    imported = vault.import_sources(tuple(jobs)) if jobs else ()
    for (data, name, primary_field), item in zip(bindings, imported):
        ref = item.summary.reference
        encoded = SourceReference(
            ref.scope.profile_id, ref.credential_id, ref.version
        ).encode()
        if name in ("client_secret", "app_secret", "api_hash"):
            data[name] = encoded
            continue
        if primary_field:
            data["source_reference"], data["auth_kind"] = encoded, "vault"
            if provider == "jira":
                data.pop("email", None)
            if provider == "twitter":
                data.pop("api_key", None)
        else:
            data.setdefault("source_auxiliary", {})[name] = encoded
        del data[name]
    commit(candidate)
    return MigrationResult(len(imported), retained, review_required, retained_derived)


ENV_MODEL_KEYS = {
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "GOOGLE_API_KEY": "google",
    "GEMINI_API_KEY": "google",
    "BYTEPLUS_API_KEY": "byteplus",
    "OPENROUTER_API_KEY": "openrouter",
    "GROK_API_KEY": "grok",
    "XAI_API_KEY": "grok",
    "DEEPSEEK_API_KEY": "deepseek",
    "MINIMAX_API_KEY": "minimax",
    "MOONSHOT_API_KEY": "moonshot",
    "GLM_API_KEY": "glm",
    "ZAI_API_KEY": "glm",
    "FUGU_API_KEY": "fugu",
    "SAKANA_API_KEY": "fugu",
    "GROQ_API_KEY": "groq",
    "MISTRAL_API_KEY": "mistral",
    "TOGETHER_API_KEY": "together",
    "FIREWORKS_API_KEY": "fireworks",
    "CEREBRAS_API_KEY": "cerebras",
    "QWEN_API_KEY": "qwen",
    "DASHSCOPE_API_KEY": "qwen",
    "NVIDIA_API_KEY": "nvidia",
    "PERPLEXITY_API_KEY": "perplexity",
    "HF_TOKEN": "huggingface",
}

ENV_OAUTH_KEYS = {
    "TELEGRAM_API_HASH": "telegram_user",
    "GOOGLE_CLIENT_SECRET": "google",
    "SLACK_SHARED_CLIENT_SECRET": "slack",
    "LINKEDIN_CLIENT_SECRET": "linkedin",
    "HUBSPOT_SHARED_CLIENT_SECRET": "hubspot",
    "FIGMA_CLIENT_SECRET": "figma",
    "NOTION_SHARED_CLIENT_SECRET": "notion",
    "SUPABASE_SHARED_CLIENT_SECRET": "supabase",
}


@sanitized_errors
def migrate_environment_document(
    vault, source_id, document, commit, *, helper_catalog=None
):
    """Explicit CraftBot .env conversion; never read/mutate process/OS environments.

    Only known model key assignments are eligible. Other settings, generated
    tokens, sessions, comments and unsupported/dynamic assignments stay exact.
    Duplicate eligible variables abort, avoiding hidden active source copies.
    """
    import json
    import re

    _label(source_id)
    raw = document.reveal()
    if not isinstance(raw, str):
        raise VaultError(Code.INVALID)
    lines, values, locations = raw.splitlines(keepends=True), {}, {}
    review_required = 0
    for index, line in enumerate(lines):
        match = re.fullmatch(
            r"(\ufeff?[ \t]*(?:export[ \t]+)?)([A-Z][A-Z0-9_]*)([ \t]*=[ \t]*)(.*?)(\r?\n)?",
            line,
        )
        if not match:
            continue
        if match[2] not in (ENV_MODEL_KEYS.keys() | ENV_OAUTH_KEYS.keys()):
            if match[4].strip() and re.search(
                r"(?:_API_KEY|_CLIENT_SECRET|_APP_SECRET|_API_HASH|_BOT_TOKEN|_SECRET_ACCESS_KEY)$",
                match[2],
            ):
                review_required += 1
            continue
        key, text = match[2], match[4].strip()
        if key in locations:
            raise VaultError(Code.CONFLICT)
        tail = ""
        locations[key] = (index, match, tail)
        if not text:
            continue
        if text.startswith('"'):
            value, end = json.JSONDecoder().raw_decode(text)
            tail = text[end:]
        elif text.startswith("'"):
            end = text.find("'", 1)
            if end < 0:
                raise VaultError(Code.INVALID)
            value, tail = text[1:end], text[end + 1 :]
        else:
            comment = re.search(r"[ \t]+#", text)
            value, tail = (
                (text[: comment.start()].rstrip(), text[comment.start() :])
                if comment
                else (text, "")
            )
        if tail.strip() and not tail.lstrip().startswith("#"):
            raise VaultError(Code.INVALID)
        locations[key] = (index, match, tail)
        if "${" in value or "`" in value or "$(" in value:
            raise VaultError(Code.INVALID)
        values[key] = value
    # Each variable is kept distinct even where two names map to one provider.
    from .catalog import oauth_helpers, authentication_helpers

    allowed_catalog = (
        model_helpers() + oauth_helpers() + authentication_helpers()
        if helper_catalog is None
        else helper_catalog
    )
    imports = []
    retained = 0
    from urllib.parse import urlsplit

    for key, value in values.items():
        if not value:
            continue
        if is_reference(value):
            retained += 1
            continue
        provider = ENV_OAUTH_KEYS[key] if key in ENV_OAUTH_KEYS else ENV_MODEL_KEYS[key]
        allowed = tuple(
            sorted(
                {
                    f"https://{urlsplit(r['endpoint']).netloc}"
                    for r in allowed_catalog
                    if r["helper"]
                    == ("oauth_" if key in ENV_OAUTH_KEYS else "model_") + provider
                    or key == "TELEGRAM_API_HASH"
                    and r["helper"] == "auth_telegram_user"
                    or key not in ENV_OAUTH_KEYS
                    and provider == "google"
                    and r["helper"] == "model_gemini"
                }
            )
        )
        if not allowed:
            raise VaultError(Code.INVALID)
        imports.append(
            (
                key,
                SourceImport(
                    uuid5(vault.profile.scope.profile_id, source_id + "/env/" + key),
                    CredentialKind.SERVICE_SECRET
                    if key == "TELEGRAM_API_HASH"
                    else CredentialKind.API_KEY,
                    provider,
                    "Environment " + key,
                    Secret(
                        {"api_hash" if key == "TELEGRAM_API_HASH" else "api_key": value}
                    ),
                    allowed,
                ),
            )
        )
    imported = (
        vault.import_sources(tuple(job for key, job in imports)) if imports else ()
    )
    for (key, job), item in zip(imports, imported):
        ref = item.summary.reference
        encoded = SourceReference(
            ref.scope.profile_id, ref.credential_id, ref.version
        ).encode()
        index, match, tail = locations[key]
        lines[index] = (
            match[1] + key + match[3] + json.dumps(encoded) + tail + (match[5] or "")
        )
    commit(Secret("".join(lines)))
    return MigrationResult(len(imported), retained, review_required=review_required)
