"""Secret-shaped text in tool results (Settings > Security > Hide secrets in results).

Cases are adapted from Hermes Agent's redaction tests
(tests/agent/test_redact.py, test_redact_non_secret_shapes.py,
test_redact_discord.py). Token-shaped literals are built by concatenation,
as Hermes does, so no realistic credential sits in the source.
"""

import base64
import time

import pytest

from app.security.output_redact import MASK, PRIVATE_KEY_MASK, redact_secrets


def _assert_idempotent(text):
    once = redact_secrets(text)
    assert redact_secrets(once) == once


# ── vendor prefixes ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "token",
    [
        "sk-proj-" + "Abc123Def456Ghi789Jkl012",
        "sk-ant-api03-" + "Zx9AbCdEfGhIjKlMnOpQ1234",
        "sk-sp-" + "ABCDEFGH1234567890" + "." + "abcdefgh1234567890_XYZ-0987654321",
        "ghp_" + "A1b2C3d4E5f6G7h8I9j0",
        "github_pat_" + "11ABCDEFG0123456789_abcdefghij",
        "xoxb-" + "123456789012-abcdefghijKLMN",
        "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "hf_" + "AbCdEfGhIjKlMnOpQrSt",
        "glpat-" + "Zx9AbCdEfGhIjKlMnOpQ",
        "gldt-" + "AbCdEfGhIjKlMnOpQrSt",
        "GR1348941" + "E" * 20,
        "ctx7sk-" + "0" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 12,
        "glsa_" + "Q7zR4Lm9Xc2Vb5Nw8Kd3Hf6JtPa0Sg7Y" + "_0123abcd",
        "xai-" + "A1b2C3d4" * 5,
        "sk_live_" + "A1b2C3d4E5f6G7h8",
    ],
)
def test_known_vendor_keys_are_masked(token):
    out = redact_secrets(f"leaked {token} in output")
    assert token not in out
    assert out.startswith("leaked [REDACTED") and out.endswith(" in output")
    _assert_idempotent(f"leaked {token} in output")


def test_the_mask_names_the_kind_of_key_but_keeps_none_of_it():
    out = redact_secrets("token " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0" + " end")
    assert out == "token [REDACTED:ghp_] end"


@pytest.mark.parametrize(
    "benign",
    [
        "the glossary explains gitlab tokens",
        "glpat-short",
        "myglpat-AbCdEfGhIjKlMnOpQrSt",
        "glsa_short",
        "glc_config_loader",
        "src/glc_renderer/backend/opengl/shaders/main.frag",
        "pip install scikit-learn",
        "backup-sk-learn-models",
        "sk-short sk-abc.def",
        "fw-short and fpk_short",
    ],
)
def test_words_that_only_look_like_prefixes_are_untouched(benign):
    assert redact_secrets(benign) == benign


def test_hashes_and_ids_are_untouched():
    benign = (
        "blob 0123456789abcdef0123456789abcdef.png\n"
        "git bundle create 0123456789abcdef0123456789abcdef01234567.bundle\n"
        "/cache/0123456789abcdef0123456789abcdef.sqlite3\n"
        "commit 0123456789abcdef0123456789abcdef01234567\n"
        "id 123e4567-e89b-12d3-a456-426614174000\n"
        "sha256:" + "ab" * 32 + "\n"
    )
    assert redact_secrets(benign) == benign


def test_zhipu_key_is_masked():
    key = "50aaed1234567890abcdef1234567890" + "." + "ZpSh99AbCdEfGh12"
    assert key not in redact_secrets(f"api_key: {key}")


# ── env dumps and .env files ────────────────────────────────────────────────


def test_a_printenv_dump_keeps_ordinary_variables():
    dump = "\n".join(
        [
            "HOME=/home/user",
            "PATH=/usr/local/bin:/usr/bin",
            "OPENAI_API_KEY=sk-proj-" + "abc123def456ghi789jkl012mno345",
            "OPENROUTER_API_KEY=sk-or-v1-" + "reallyLongSecretKeyValue12345678",
            "TELEGRAM_BOT_TOKEN=bot987654321:" + "ABCDEfghij-KLMNopqrst_UVWXyz12345",
            "DB_PASSWORD=hunter2",
            "CUSTOM_TOKEN=opaqueValue" + "123456789",
            "SHELL=/bin/bash",
            "USER=craftbot",
        ]
    )
    out = redact_secrets(dump)
    for secret in ("abc123def456", "reallyLongSecretKey", "ABCDEfghij", "hunter2", "opaqueValue123"):
        assert secret not in out
    for kept in ("HOME=/home/user", "PATH=/usr/local/bin:/usr/bin", "SHELL=/bin/bash", "USER=craftbot"):
        assert kept in out
    assert "DB_PASSWORD=[REDACTED]" in out
    _assert_idempotent(dump)


def test_env_file_quotes_and_export_are_kept():
    out = redact_secrets('export SECRET_TOKEN="mypassword"\nAPI_KEY=\'Zq8vN3pL6xR2tY9wB4m\'\n')
    assert out == 'export SECRET_TOKEN="[REDACTED]"\nAPI_KEY=\'[REDACTED]\'\n'


@pytest.mark.parametrize(
    "text",
    [
        "MAX_TOKENS=100",
        "KEYBOARD=notsecret",
        "PASSAGE=notsecret",
        "REDACT_SECRETS=False",
        "API_KEY=os.getenv('OPENAI_API_KEY')",
        "SSH_AUTH_SOCK=$HOME/.ssh/agent.sock",
        "SSH_AUTH_SOCK=/run/user/$UID/keyring/ssh",
        "export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket)",
        "DOCKER_AUTH_CONFIG=/home/u/.docker",
        "MY_KEY_PATH=~/.ssh/id_rsa",
        "SECRET_DIR=/etc",
        "IDENTITY_TOKEN=bailu",
    ],
)
def test_references_literals_and_short_scalars_stay_readable(text):
    assert redact_secrets(text) == text


@pytest.mark.parametrize(
    "line, cleartext",
    [
        ("AWS_SECRET_ACCESS_KEY=/wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMIK7MDENG"),
        ("API_SECRET=$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaHZhbHVl", "argon2id"),
        ("SESSION_SECRET=/8f3kd9sKd0alsKDJ2mfkeisl3kdMc9dksla", "8f3kd9sKd0als"),
        ("PGPASSWORD=s3cret", "s3cret"),
    ],
)
def test_secrets_that_start_like_a_path_or_variable_are_still_masked(line, cleartext):
    assert cleartext not in redact_secrets(line)


@pytest.mark.parametrize(
    "source",
    [
        "MAX_TOKENS = 100",
        '    api_key = os.getenv("OPENAI_API_KEY")',
        '{"apiKey": "test", "token": "CPU"}',
        "def get_token(self):\n    return self._token",
        'password = input("Password: ")',
    ],
)
def test_source_code_assignments_are_untouched(source):
    assert redact_secrets(source) == source


# ── private keys ────────────────────────────────────────────────────────────


def test_a_whole_private_key_block_is_masked():
    pem = (
        "before\n-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
        "QyNTUxOQAAACDx7Wq4kQ1hP3lJm9X2yVZr0cE8QfKqUo8dQ5n5gZ9bAAAAJhYb3JxWG9y\n"
        "-----END OPENSSH PRIVATE KEY-----\nafter"
    )
    assert redact_secrets(pem) == f"before\n{PRIVATE_KEY_MASK}\nafter"


def test_the_body_of_a_partial_key_print_is_masked():
    head = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1x7Wq4kQ1hP3lJm9X2yVZr0cE8QfKqUo8dQ5n5gZ9bAAAAJhY\n"
        "b3JxWG9yb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAA\n"
        "$ echo done"
    )
    out = redact_secrets(head)
    assert "MIIEowIBAAKCAQEA" not in out and "b3JxWG9y" not in out
    assert out.endswith("$ echo done")


def test_a_base64_encoded_pem_key_is_masked_but_other_base64_is_not():
    blob = base64.b64encode(
        b"-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n"
    ).decode()
    assert redact_secrets(f"client-key-data: {blob}") == f"client-key-data: {PRIVATE_KEY_MASK}"
    cert = base64.b64encode(b"-----BEGIN CERTIFICATE-----\n" + b"A" * 60).decode()
    assert redact_secrets(cert) == cert


def test_an_age_secret_key_is_masked():
    key = "AGE-SECRET-KEY-1" + "QQPZ8YH4GJ0TXK8Q5ZSPWJ6X7Y3V2N4M8R0L9C2F5D3H7G6B1A0E9W8"
    assert redact_secrets(key) == PRIVATE_KEY_MASK


# ── command-line flags ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command, secret",
    [
        ("mysql --password=s3cretPassw0rd -h db", "s3cretPassw0rd"),
        ("tool --api-key Zq8vN3pL6xR2tY9wB4m run", "Zq8vN3pL6xR2tY9wB4m"),
        ('gh auth --token "Zq8 vN3pL6xR2tY9wB4m"', "vN3pL6xR2tY9wB4m"),
        ("docker login -u me -p Zq8vN3pL6xR2tY9wB4m registry.example", "Zq8vN3pL6xR2tY9wB4m"),
        (
            "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=Zq8vN3pL6xR2tY9wB4mAbCd==;EndpointSuffix=core",
            "Zq8vN3pL6xR2tY9wB4mAbCd",
        ),
    ],
)
def test_credentials_passed_as_flags_are_masked(command, secret):
    out = redact_secrets(command)
    assert secret not in out
    _assert_idempotent(command)


@pytest.mark.parametrize(
    "text",
    [
        "psql --password -h db",
        "  --token TOKEN        Access token",
        "  [--password PASSWORD]",
        "use --token to pass a token",
        "curl --token 60",
        "mysql --password=$DB_PASS",
        "gcloud --credentials ~/.config/gcloud/creds.json",
        "tool --api-key sk-or-v1-xxx",
    ],
)
def test_help_text_variables_and_paths_after_flags_are_kept(text):
    assert redact_secrets(text) == text


# ── headers ─────────────────────────────────────────────────────────────────


def test_authorization_headers_keep_the_scheme():
    credential = "opaque" + "Cred3ntialValue0123456789"
    out = redact_secrets(f'curl -H "Authorization: Bearer {credential}" https://api')
    assert credential not in out
    assert out == 'curl -H "Authorization: Bearer [REDACTED]" https://api'
    assert out.count('"') == 2


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Basic",
        "Send the `Authorization: Bearer` header.",
        "(Proxy-Authorization: Basic)",
        "the authorization flow is described below",
    ],
)
def test_authorization_prose_is_kept(text):
    assert redact_secrets(text) == text


def test_api_key_and_cookie_headers_are_masked():
    dump = (
        "> GET /v1 HTTP/1.1\n"
        "> x-api-key: opaqueValue12345678\n"
        "< set-cookie: session=Zq8vN3pL6xR2tY9wB4m; Path=/\n"
        "< content-type: application/json\n"
    )
    out = redact_secrets(dump)
    assert "opaqueValue12345678" not in out and "Zq8vN3pL6xR2tY9wB4m" not in out
    assert "> x-api-key: [REDACTED]" in out
    assert "< content-type: application/json" in out
    _assert_idempotent(dump)


def test_api_key_header_in_a_curl_command_is_masked():
    out = redact_secrets("curl -H 'x-api-key: opaqueValue12345678' https://api.example.com")
    assert out == "curl -H 'x-api-key: [REDACTED]' https://api.example.com"


# ── Telegram, JWT, Discord ──────────────────────────────────────────────────


def test_telegram_bot_tokens_keep_the_bot_id():
    out = redact_secrets("bot123456789:" + "ABCDEfghij-KLMNopqrst_UVWXyz12345")
    assert out == f"bot123456789:{MASK}"


def test_a_long_digit_run_stays_fast():
    text = "_typelessdata: " + "0" * 100_000 + "\n"
    start = time.perf_counter()
    assert redact_secrets(text) == text
    assert time.perf_counter() - start < 1.0


def test_jwts_are_masked_with_the_text_around_them_kept():
    jwt = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N"
    assert redact_secrets(f"token={jwt}; next") == f"token={MASK}; next"


def test_discord_bot_tokens_are_masked_only_when_the_id_decodes():
    user_id = base64.urlsafe_b64encode(b"123456789012345678").decode().rstrip("=")
    token = user_id + "." + "GhIjKl" + "." + "AbCdEfGhIjKlMnOpQrStUvWxYz0123"
    assert token not in redact_secrets(f"DISCORD token {token} end")
    lookalike = "MyVeryLongClassNameHereXY" + "." + "Config" + "." + "AnotherLongAttributeNameValue"
    assert redact_secrets(lookalike) == lookalike


# ── URLs ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, secret",
    [
        ("postgres://admin:dbpass@db.internal:5432/app", "dbpass"),
        ("mongodb+srv://u:Zq8vN3pL6x@cluster0.example.net/db", "Zq8vN3pL6x"),
        ("git remote set-url origin https://Zq8vN3pL6xR2tY9w@github.com/o/r.git", "Zq8vN3pL6xR2tY9w"),
        ("https://user:hunter2pass@proxy.example.com/v1", "hunter2pass"),
        ("https://hooks.slack.com/services/T000/B000/" + "XXXXXXXXXXXXXXXXXXXXXXXX", "XXXXXXXXXXXXXXXX"),
    ],
)
def test_credentials_inside_urls_are_masked(url, secret):
    assert secret not in redact_secrets(url)
    _assert_idempotent(url)


@pytest.mark.parametrize(
    "text",
    [
        "GET https://api.example.com/oauth/cb?code=abc123xyz789&state=csrf_ok",
        'url = f"postgresql://{user}:{password}@{host}/db"',
        "redis://:${REDIS_PASSWORD}@cache:6379",
        "https://user:password@host/docs-example",
        "https://example.com/users/alice@example.com/profile",
        "ssh://git@github.com/o/r.git",
        "postgres://db.internal:5432/app",
    ],
)
def test_ordinary_urls_and_templates_are_kept(text):
    assert redact_secrets(text) == text


# ── general ─────────────────────────────────────────────────────────────────


def test_empty_and_non_string_values_pass_through():
    assert redact_secrets("") == ""
    assert redact_secrets(None) is None


def test_ordinary_output_is_returned_unchanged():
    text = (
        "total 48\n"
        "drwxr-xr-x  5 user user 4096 Nov 25 10:00 .\n"
        "-rw-r--r--  1 user user  220 Nov 25 10:00 README.md\n"
        "def tokenize(text: str) -> list[str]:\n"
        "    return text.split()\n"
        "Ran 42 tests in 0.31s: OK\n"
        "See https://docs.python.org/3/library/re.html for details.\n"
    )
    assert redact_secrets(text) == text


def _ordinary_shell_output(size: int) -> str:
    lines = [
        "drwxr-xr-x  5 user user 4096 Nov 25 10:00 src",
        "-rw-r--r--  1 user user 1234 Nov 25 10:00 app/security/policy.py",
        "commit 0123456789abcdef0123456789abcdef01234567",
        "Author: Someone <someone@example.com>",
        "    Fix the parser: handle quotes, escapes and comments.",
        "test_security_gate.py::test_review PASSED  [ 42%]",
        "GET https://example.com/api/v1/items?page=2 200 OK",
        "PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    out, i = [], 0
    while sum(len(line) + 1 for line in out) < size:
        out.append(lines[i % len(lines)])
        i += 1
    return "\n".join(out)


def test_ten_kilobytes_of_ordinary_output_take_well_under_a_few_milliseconds():
    text = _ordinary_shell_output(10_000)
    redact_secrets(text)  # warm up
    runs = 50
    start = time.perf_counter()
    for _ in range(runs):
        assert redact_secrets(text) == text
    per_call_ms = (time.perf_counter() - start) / runs * 1000
    assert per_call_ms < 5.0, f"{per_call_ms:.2f} ms per 10 KB"


def test_ten_kilobytes_with_secrets_stay_fast():
    text = _ordinary_shell_output(10_000) + "\nOPENAI_API_KEY=sk-proj-" + "Abc123Def456Ghi789Jkl012\n"
    start = time.perf_counter()
    for _ in range(20):
        out = redact_secrets(text)
    per_call_ms = (time.perf_counter() - start) / 20 * 1000
    assert "Abc123Def456" not in out
    assert per_call_ms < 10.0, f"{per_call_ms:.2f} ms per 10 KB"


@pytest.mark.parametrize(
    "text",
    [
        "postgres://user:" + "a" * 50_000 + " no at sign",
        "https://" + "a" * 50_000,
        "x-api-key: " + "&" * 50_000,
        "--password " + '"' + "a" * 50_000,
        "-----BEGIN RSA PRIVATE KEY-----\n" + "A" * 50_000,
        "Private-Lines: 3\n" + "A" * 50_000,
    ],
)
def test_pathological_input_stays_linear(text):
    start = time.perf_counter()
    redact_secrets(text)
    assert time.perf_counter() - start < 1.0
