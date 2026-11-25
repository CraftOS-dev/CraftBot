"""Static scan of a skill before it is installed (Settings > Security > Scan skills).

Ported from OpenClaw (MIT, OpenClaw Foundation) ``src/skills/security/
scanner.ts`` and ``skill-bundle-scan.ts``: the skill-text rules (literal
secrets, pipe-to-shell, secret exfiltration, broad deletes, chmod 777), the
JavaScript source rules (child_process exec, eval, crypto mining, env
harvesting, exfiltration, obfuscation), its limits (500 files, 1 MB a file,
dot-files and node_modules skipped) and its severities: a ``critical``
finding blocks the install, a ``warn`` finding is reported.

Hermes Agent's ``tools/skills_guard.py`` (MIT, Nous Research) adds the rules
for Python and shell skills OpenClaw's scanner does not cover: reverse
shells, DNS and /tmp-staging exfiltration, reading credential files,
destructive system commands, sudoers and SSH persistence, writes into agent
instruction files, embedded provider tokens, invisible characters, code
hidden after long padding, binaries and symlinks that leave the skill.
Hermes' ``critical`` rules are critical here; its ``high`` rules are
warnings; its medium and low rules are left out.

Calibrated against CraftBot's own 195 skills, where the rules as ported
blocked 58: a secret variable sent with curl/fetch (how API skills
authenticate) and a generic ``token = "..."`` (placeholders) are warnings,
with OpenClaw's exact token shapes still critical; ``echo ... | python``
counts only when the interpreter runs the piped text, not a script; the
root-delete rule counts the root or a top-level folder (``/path/to/x`` is
not); writes into other agents' instruction files (CLAUDE.md, AGENTS.md)
are warnings, and writes into CraftBot's own (AGENT.md, SOUL.md, USER.md,
MEMORY.md, PROACTIVE.md) are critical.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from app.security.threats import FORGET_RULES_RAW_RE, mask_negated_forget

CRITICAL = "critical"
WARN = "warn"


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    severity: str  # "critical" | "warn"
    message: str
    evidence: str = ""


# OpenClaw's limits.
MAX_FILES = 500
MAX_FILE_BYTES = 1024 * 1024
_MAX_PER_RULE = 32
_MAX_FINDINGS = 200

# ── OpenClaw: skill text rules ──

_LITERAL_SECRET = re.compile(
    r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35})(?![A-Za-z0-9_-])"
    r"|-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----\r?\n(?=(?:[A-Za-z0-9+/=]\r?\n?){48,}-----END \1-----)"
    r"(?:[A-Za-z0-9+/=]+\r?\n)+-----END \1-----"
)


@dataclass(frozen=True)
class _Rule:
    rule: str
    severity: str
    message: str
    pattern: re.Pattern
    context: Optional[re.Pattern] = None  # must also match the whole source
    window: Optional[int] = None  # ...within this many lines of the match


_SKILL_TEXT_RULES = [
    _Rule("literal-secret", CRITICAL, "contains a recognized literal credential", _LITERAL_SECRET),
    _Rule("shell-pipe-to-shell", CRITICAL, "pipes a download into a shell",
          re.compile(r"\b(curl|wget)\b[^|\n]{0,120}\|\s*(sh|bash|zsh)\b", re.I)),
    _Rule("secret-exfiltration", CRITICAL, "may send environment variables out",
          re.compile(r"\b(process\.env|env)\b.{0,80}\b(fetch|curl|wget|http|https)\b", re.I)),
    _Rule("destructive-delete", WARN, "contains a broad delete command",
          re.compile(r"\brm\s+-rf\s+(\/|\$HOME|~|\.)", re.I)),
    _Rule("unsafe-permissions", WARN, "makes files world-writable",
          re.compile(r"\bchmod\s+(-R\s+)?777\b", re.I)),
]

# ── OpenClaw: JavaScript source rules ──

_NETWORK_SEND = re.compile(r"\bfetch\s*\(|\bpost\s*\(|\.\s*post\s*\(|http\.request\s*\(", re.I)
_SOURCE_RULES = [
    _Rule("potential-exfiltration", WARN, "reads files and sends over the network",
          re.compile(r"readFileSync|readFile"), _NETWORK_SEND),
    _Rule("obfuscated-code", WARN, "contains a hex-encoded string",
          re.compile(r"(\\x[0-9a-fA-F]{2}){6,}")),
    _Rule("obfuscated-code", WARN, "decodes a large base64 payload",
          re.compile(r"(?:atob|Buffer\.from)\s*\(\s*[\"'][A-Za-z0-9+/=]{200,}[\"']")),
    _Rule("env-harvesting", CRITICAL, "reads environment variables and sends over the network",
          re.compile(r"process\.env"), _NETWORK_SEND, 8),
]
_EXEC_METHODS = ("exec", "execSync", "spawn", "spawnSync", "execFile", "execFileSync")
_DANGEROUS_EXEC = re.compile(
    r"\b(exec|execSync|spawn|spawnSync|execFile|execFileSync)\s*\("
    r"|[\"'](exec|execSync|spawn|spawnSync|execFile|execFileSync)[\"']\s*\]\s*\("
)
_DYNAMIC_CODE = re.compile(r"\beval\s*\(|new\s+Function\s*\(")
_CRYPTO_MINING = re.compile(r"stratum\+tcp|stratum\+ssl|coinhive|cryptonight|xmrig", re.I)
_WEBSOCKET_PORT = re.compile(r"new\s+WebSocket\s*\(\s*[\"']wss?:\/\/[^\"']*:(\d+)")
_STANDARD_PORTS = {80, 443, 8080, 8443, 3000}
_CP_NAMED = re.compile(r"\bimport\s*\{([^}]*)\}\s*from\s*[\"'](?:node:)?child_process[\"']"
                       r"|\b(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\s*\(\s*[\"'](?:node:)?child_process[\"']\s*\)")
_CP_NAMESPACE = re.compile(r"\bimport\s+(\w+)\s+from\s*[\"'](?:node:)?child_process[\"']"
                           r"|\bimport\s*\*\s*as\s+(\w+)\s+from\s*[\"'](?:node:)?child_process[\"']"
                           r"|\b(?:const|let|var)\s+(\w+)\s*=\s*require\s*\(\s*[\"'](?:node:)?child_process[\"']\s*\)")
_CP_RECEIVERS = {"cp", "childProcess", "child_process"}

# ── Hermes: Python and shell rules (critical stays critical, high is a warning) ──

_SHELLS = r"(?:bash|sh|zsh|ksh|dash)\b"
_SUDO = r"(?:sudo\s+(?:-\S+\s+)*)?"
_CRED_FILE = (r"(?:\.ssh[/\\]id_(?:rsa|ed25519|ecdsa|dsa)(?!\.pub)|\.env\b|credentials\b|\.netrc\b"
              r"|\.pgpass\b|\.npmrc\b|\.pypirc\b)")
_CRED_LITERAL = r"[\"'][^\"'\n]*" + _CRED_FILE + r"[^\"'\n]*[\"']"
_PY_CRED_ARG = r"(?:os\.path\.expanduser\s*\(\s*)?" + _CRED_LITERAL + r"\s*\)?"
_LOOPBACK = r"(?![^\n]*https?://(?:localhost|127\.0\.0\.1|\[::1\]))"
_MODIFY_VERB = (r"(?:\bwrit(?:e|es|ing)\b|\bwritten\b|\bedit(?:s|ed|ing)?\b"
                r"|\bmodif(?:y|ies|ied|ying|ication)s?\b|\bupdat(?:e|es|ed|ing)\b"
                r"|\bappend(?:s|ed|ing)?\b|\bprepend(?:s|ed|ing)?\b"
                r"|\binject(?:s|ed|ing)?\b|\boverwrit(?:e|es|ing)\b|\boverwritten\b"
                r"|\breplac(?:e|es|ed|ing)\b|\balter(?:s|ed|ing)?\b|\badd(?:s|ed|ing)\b)")
_OTHER_AGENT_FILES = r"(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules)"
_CRAFTBOT_FILES = r"(?:AGENT\.md|SOUL\.md|USER\.md|MEMORY\.md|PROACTIVE\.md)"


def _shell_write(files: str) -> str:
    return (
        rf"(?:>>|[\w\"'`)\]]\s*>)\s*[~\w./-]*{files}(?!\.?\w)"
        rf"|\bsed\b[^\n]*\s(?:-[A-Za-z]*i[A-Za-z]*|--in-place)\b[^\n]*{files}(?!\.?\w)"
        rf"|\btee\s+(?:-a\s+)?[~\w./\"'-]*{files}(?!\.?\w)"
        rf"|\b(?:cp|mv)\s+[^\s|;&]+\s+[^\n|;&]{{0,40}}?{files}(?!\.?\w)"
    )


def _prose_modify(files: str) -> str:
    return (
        rf"^\s*(?:[-*+]\s+|\d+[.)]\s+)?{_MODIFY_VERB}[^\n,]{{0,80}}?{files}\b"
        rf"|(?:\byou\s+(?:must|should|need\s+to)\s+|\bplease\s+"
        rf"|\bmake\s+sure\s+(?:to\s+|you\s+)|\bbe\s+sure\s+to\s+)"
        rf"{_MODIFY_VERB}[^\n,]{{0,80}}?{files}\b"
    )


_HERMES = [
    # Exfiltration
    (rf"curl\s+{_LOOPBACK}[^\n]*\$\{{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b", "env_exfil_curl", WARN,
     "curl sends a secret environment variable"),
    (rf"wget\s+{_LOOPBACK}[^\n]*\$\{{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b", "env_exfil_wget", WARN,
     "wget sends a secret environment variable"),
    (rf"fetch\s*\({_LOOPBACK}[^\n]*\$\{{?\w*(?:KEY|TOKEN|SECRET|PASSWORD)S?\b", "env_exfil_fetch", WARN,
     "fetch() sends a secret environment variable"),
    (rf"httpx?\.(get|post|put|patch)\s*\({_LOOPBACK}[^\n]*(KEY|TOKEN|SECRET|PASSWORD)", "env_exfil_httpx", WARN,
     "an HTTP call sends a secret variable"),
    (rf"requests\.(get|post|put|patch)\s*\({_LOOPBACK}[^\n]*(KEY|TOKEN|SECRET|PASSWORD)", "env_exfil_requests",
     WARN, "an HTTP call sends a secret variable"),
    (r"cat\s+(?!>)[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets_file", CRITICAL,
     "reads a secrets file"),
    (r"\b(?:readFile(?:Sync)?|readTextFile)\s*\(\s*" + _CRED_LITERAL, "js_read_secrets_file", CRITICAL,
     "reads a credential file"),
    (r"\bopen\s*\(\s*" + _PY_CRED_ARG
     + r"(?!\s*\)?\s*,\s*[\"'][^\"']*[wax][^\"']*[\"'])(?![^\n]*\bmode\s*=\s*[\"'][^\"']*[wax])"
     + r"|\bPath\s*\(\s*" + _PY_CRED_ARG + r"\s*\)\.(?:read_text|read_bytes|readlines|readline)\s*\(",
     "py_read_secrets_file", CRITICAL, "reads a credential file"),
    (r"(?<![-/])\b(?:dig|nslookup)\s+(?:[-+@]\S*(?:\s+[^\s$\"'-][^\s$]*)?\s+)*[\"']?[^\s\"'$()]*"
     r"\$(?:\{[^}\s]*\}|\([^\n]*?\)+|\w+)[\w-]*[\"']?\.[a-z]"
     r"|(?<![-/])\bhost\s+(?:[-+@]\S*(?:\s+[^\s$\"'-][^\s$]*)?\s+)*[\"']?[^\s\"'$()]*"
     r"\$(?:\{[^}\s]*\}|\([^\n]*?\)+|\w+)[\w-]*\.[a-z]"
     r"|(?:^|[;&|]|\$\(|\b(?:do|then|else)\b)\s*host\s+(?:[-+@]\S*(?:\s+[^\s$\"'-][^\s$]*)?\s+)*[\"']?\$",
     "dns_exfil", CRITICAL, "DNS lookup carrying data (DNS exfiltration)"),
    (r">\s*/tmp/[^\s]*\s*&&\s*(curl|wget|nc|python)", "tmp_staging", CRITICAL,
     "stages data in /tmp, then sends it"),
    (r"\$HOME/\.ssh|\~/\.ssh", "ssh_dir_access", WARN, "uses the SSH folder"),
    (r"\$HOME/\.aws|\~/\.aws", "aws_dir_access", WARN, "uses AWS credentials"),
    (r"\$HOME/\.gnupg|\~/\.gnupg", "gpg_dir_access", WARN, "uses the GPG keyring"),
    (r"\$HOME/\.kube|\~/\.kube", "kube_dir_access", WARN, "uses Kubernetes config"),
    (r"\$HOME/\.docker|\~/\.docker", "docker_dir_access", WARN, "uses Docker config"),
    (r"printenv|(?<![A-Za-z0-9_])env\s*\|(?!\|)(?!\s*[{(])", "dump_all_env", WARN,
     "dumps every environment variable"),
    (r"process\.env\[", "node_process_env", WARN, "reads process.env"),
    (r"!\[.*\]\(https?://[^\)]*\$\{?", "md_image_exfil", WARN, "image URL carrying a variable"),
    (r"\[[^\[]*\]\(https?://[^\)]*\$\{?", "md_link_exfil", WARN, "link URL carrying a variable"),
    (r"(send|post|upload|transmit)\s+.*\s+(to|at)\s+https?://", "send_to_url", WARN,
     "tells the agent to send data to a URL"),
    # Prompt injection
    (r"ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+instructions", "prompt_injection_ignore", CRITICAL,
     "tells the agent to ignore its instructions"),
    (r"system\s+(?:\w+\s+)*prompt\s+(?:\w+\s+)*override", "sys_prompt_override", CRITICAL,
     "tries to override the system prompt"),
    (r"disregard\s+(?:\w+\s+)*(your|all|any)\s+(?:\w+\s+)*(instructions|rules|guidelines)", "disregard_rules",
     CRITICAL, "tells the agent to disregard its rules"),
    (r"act\s+as\s+(if|though)\s+(?:\w+\s+)*you\s+(?:\w+\s+)*(have\s+no|don\'t\s+have)\s+(?:\w+\s+)*"
     r"(restrictions|limits|rules)", "bypass_restrictions", CRITICAL, "tells the agent to act without restrictions"),
    (r"translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)", "translate_execute", CRITICAL,
     "translate-then-execute evasion"),
    (r"(respond|answer|reply)\s+without\s+(?:\w+\s+)*(restrictions|limitations|filters|safety)", "remove_filters",
     CRITICAL, "tells the agent to drop its safety rules"),
    (r"\bDAN\s+mode\b|Do\s+Anything\s+Now", "jailbreak_dan", CRITICAL, "jailbreak attempt"),
    (r"\bdeveloper\s+mode\b.*\benabled?\b", "jailbreak_dev_mode", CRITICAL, "jailbreak attempt"),
    (r"you\s+are\s+(?:\w+\s+)*now\s+", "role_hijack", WARN, "tries to give the agent a new role"),
    (r"do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user(?!\s+to\s+[\"'“‘])"
     r"(?!.*\b(?:unless|except|until|confirm|diagnos\w*|verify|check)\b)", "deception_hide", WARN,
     "tells the agent to hide something from the user"),
    (r"pretend\s+(?:\w+\s+)*(you\s+are|to\s+be)\s+", "role_pretend", WARN, "makes the agent pretend"),
    (FORGET_RULES_RAW_RE, "forget_rules", WARN, "tells the agent to forget its instructions"),
    (r"output\s+(?:\w+\s+)*(system|initial)\s+prompt", "leak_system_prompt", WARN, "extracts the system prompt"),
    (r"(when|if)\s+no\s*one\s+is\s+(watching|looking)", "conditional_deception", WARN,
     "behaves differently when unobserved"),
    (r"you\s+have\s+been\s+(?:\w+\s+)*(updated|upgraded|patched)\s+to", "fake_update", WARN, "fake update"),
    (r"hypothetical\s+scenario.*(?:ignore|bypass|override)", "hypothetical_bypass", WARN,
     "hypothetical used to bypass rules"),
    (r"<!--[^>]*(?:\b(?:ignore|forget|disregard|override)\s+(?:\w+\s+)*?"
     r"(?:previous|prior|above|earlier|all|any|your|the)\s+(?:\w+\s+)*?"
     r"(?:instructions?|rules|prompts?|guidelines|directions|restrictions)"
     r"|\bsystem\s*(?:prompt|message|instructions?|override)|\b(?:override|secret|hidden|system)\s*:"
     r"|\b(?:ignore|override|bypass|disable)\s+(?:\w+\s+)*?(?:safety|security|guardrails|filters)\b"
     r"|\b(?:secret|hidden|new)\s+(?:instructions?|commands?|directives?|tasks?)\b|\byou\s+are\s+now\b"
     r"|\bdo\s+not\s+(?:tell|reveal|show|mention|inform)\b"
     r"|\b(?:note|message)\s+(?:to|for)\s+(?:the\s+)?(?:ai|agent|assistant|model|llm)\b)[^>]*-->",
     "html_comment_injection", WARN, "hides instructions in an HTML comment"),
    (r"<\s*div\s+style\s*=\s*[\"'][\s\S]*?display\s*:\s*none", "hidden_div", WARN,
     "hides instructions in an invisible block"),
    # Destructive
    (r"rm\s+-rf\s+(?:--no-preserve-root\s+)?/"
     r"(?!(?:tmp|var/tmp|dev/shm|run)(?:\b|/))(?:\*|[\w.-]+/?\*?)?(?=[\s;&|'\"`)]|$)",
     "destructive_root_rm", CRITICAL, "deletes the root folder or a top-level folder"),
    (r"(?<![A-Za-z0-9])rm\s+(-[^\s]*)?r.*(?:\$HOME|~[/\s*]|~$)|(?<![A-Za-z0-9])rmdir\s+.*(?:\$HOME|~[/\s*]|~$)",
     "destructive_home_rm", CRITICAL, "deletes the home folder"),
    (r">\s*/etc/", "system_overwrite", CRITICAL, "overwrites system configuration"),
    (r"\bmkfs\b", "format_filesystem", CRITICAL, "formats a filesystem"),
    (r"\bdd\s+.*if=.*of=/dev/", "disk_overwrite", CRITICAL, "writes a raw disk"),
    (r"truncate\s+-s\s*0\s+/", "truncate_system", CRITICAL, "empties a system file"),
    (r"shutil\.rmtree\s*\(\s*[\"\'/]", "python_rmtree", WARN, "deletes an absolute folder tree"),
    # Persistence and privilege escalation
    (r"authorized_keys", "ssh_backdoor", CRITICAL, "changes SSH authorized_keys"),
    (r"/etc/sudoers|visudo", "sudoers_mod", CRITICAL, "changes sudoers"),
    (r"NOPASSWD", "nopasswd_sudo", CRITICAL, "passwordless sudo entry"),
    (r"(?<![a-z])set(?:e|re|res)?[ug]id\s*\(|\bcap_set[ug]id\b"
     r"|\bchmod\s+(?:-\w+\s+)*(?:[ugoa]*[+=][rwxXt]*s|0?[2-7][0-7]{3}\b)", "setuid_setgid", CRITICAL,
     "sets setuid/setgid"),
    (_prose_modify(_OTHER_AGENT_FILES), "agent_config_mod", WARN, "tells the agent to change another agent's instructions"),
    (_shell_write(_OTHER_AGENT_FILES), "agent_config_mod_shell", WARN, "writes into another agent's instruction file"),
    (_shell_write(_CRAFTBOT_FILES), "craftbot_config_mod_shell", CRITICAL, "writes into CraftBot's instruction files"),
    (_prose_modify(_CRAFTBOT_FILES), "craftbot_config_mod", WARN, "tells the agent to change CraftBot's instructions"),
    (rf"{_OTHER_AGENT_FILES}\b[^\n]{{0,40}}?\b(?:should|must|needs?\s+to)\s+(?:contain|say|include|have|list)\b",
     "agent_config_contract", WARN, "dictates an agent instruction file's contents"),
    # Network
    (r"\bnc\s+-[lp]|ncat\s+-[lp]|\bsocat\b[^\n]*\b(?:tcp|udp|openssl|ssl|exec|system|pty|unix)[\w-]*:",
     "reverse_shell", CRITICAL, "reverse shell listener"),
    (rf"/bin/{_SHELLS}\s+-i\s+.*>/dev/tcp/", "bash_reverse_shell", CRITICAL, "reverse shell over /dev/tcp"),
    (r"python[23]?\s+-c\s+[\"']import\s+socket", "python_socket_oneliner", CRITICAL, "Python socket one-liner"),
    (r"socket\.connect\s*\(\s*\(", "python_socket_connect", WARN, "opens a raw socket"),
    (r"\bngrok\b|\blocaltunnel\b|\bserveo\b|\bcloudflared\b", "tunnel_service", WARN, "uses a tunnel service"),
    (r"0\.0\.0\.0:\d+|INADDR_ANY", "bind_all_interfaces", WARN, "listens on every network interface"),
    (r"webhook\.site|requestbin\.com|pipedream\.net|hookbin\.com", "exfil_service", WARN,
     "uses a data-collection service"),
    # Obfuscation and execution
    (r"(?:\bbase64\s+(?:-[^\s|]+\s+)*?(?:-[a-z]*d[a-z]*|--decode)\b|\bopenssl\s+(?:base64|enc)\b[^|;&\n]*?\s-d\b)"
     r"[^\n]*?(?:\||;|&&)\s*(?:\w+=\S*\s+)*(?:\S*/)?"
     r"(?:sh|bash|zsh|ksh|dash|fish|python[\d.]*|perl|ruby|node|nodejs|php|eval|source|exec|xargs|env|sudo"
     r"|iex|pwsh|powershell|tar|bsdtar|unzip|cpio|gunzip|gzip|zcat|xz|unxz|bunzip2|\.(?=\s))(?![\w.-])"
     r"|\b(?:eval|source|iex|exec)\b[^\n]*\bbase64\s+(?:-[^\s|]+\s+)*?(?:-[a-z]*d[a-z]*|--decode)\b",
     "base64_decode_pipe", WARN, "decodes base64 into an interpreter"),
    (rf"echo\s+[^\n]*\|\s*(?:{_SHELLS}|python[\d.]*|perl|ruby|node)(?:\s+-)?\s*(?:$|[;&|)`])", "echo_pipe_exec",
     CRITICAL, "pipes text into an interpreter to run"),
    (r"(?<![.\w])exec\s*\(\s*[\"'](?!(?-i:PRAGMA|BEGIN|COMMIT|ROLLBACK|CREATE|INSERT|SELECT|UPDATE|DELETE|DROP|ALTER"
     r"|VACUUM|SAVEPOINT|RELEASE|ANALYZE|REINDEX|ATTACH|DETACH|REPLACE)\b)", "exec_string", WARN,
     "exec() of a string"),
    (r"compile\s*\(\s*[^\)]+,\s*[\"'].*[\"']\s*,\s*[\"']exec[\"']\s*\)", "python_compile_exec", WARN,
     "compiles code to run"),
    (r"getattr\s*\(\s*__builtins__", "python_getattr_builtins", WARN, "dynamic access to builtins"),
    (r"__import__\s*\(\s*[\"']os[\"']\s*\)", "python_import_os", WARN, "dynamic import of os"),
    (r"chr\s*\(\s*\d+\s*\)\s*\+\s*chr\s*\(\s*\d+", "chr_building", WARN, "builds strings from chr()"),
    (r"os\.system\s*\(", "python_os_system", WARN, "runs a shell command"),
    (r"os\.popen\s*\(", "python_os_popen", WARN, "runs a shell pipe"),
    (r"child_process\.(exec|spawn|fork)\s*\(", "node_child_process", WARN, "runs a child process"),
    (r"Runtime\.getRuntime\(\)\.exec\(", "java_runtime_exec", WARN, "runs a shell command"),
    # Traversal
    (r"\.\./\.\./\.\.", "path_traversal_deep", WARN, "deep relative path traversal"),
    (r"/etc/passwd|/etc/shadow", "system_passwd_access", CRITICAL, "uses system password files"),
    (r"/proc/self|/proc/\d+/", "proc_access", WARN, "reads another process's data"),
    # Supply chain
    (rf"curl\s+[^|\s][^\n]*\|\s*{_SUDO}{_SHELLS}", "curl_pipe_shell", CRITICAL, "pipes a download into a shell"),
    (rf"wget\s+[^\n]*-O\s*-\s*\|\s*{_SUDO}{_SHELLS}", "wget_pipe_shell", CRITICAL, "pipes a download into a shell"),
    (rf"curl\s+[^|\s][^\n]*\|\s*{_SUDO}python", "curl_pipe_python", CRITICAL, "pipes a download into Python"),
    (r"xmrig|stratum\+tcp|monero|coinhive|cryptonight", "crypto_mining", CRITICAL, "crypto mining"),
    # Embedded credentials
    (r"(?:api[_-]?key|token|secret|password)\s*[=:]\s*[\"']"
     r"(?!(?-i:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)[\"'])[A-Za-z0-9+/=_-]{20,}", "hardcoded_secret", WARN,
     "contains a hardcoded secret"),
    (r"(?-i:-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----)", "embedded_private_key", CRITICAL, "contains a private key"),
    (r"(?-i:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,})", "github_token_leaked", CRITICAL,
     "contains a GitHub token"),
    (r"(?-i:sk-[A-Za-z0-9]{20,})", "openai_key_leaked", CRITICAL, "contains an OpenAI key"),
    (r"(?-i:sk-ant-[A-Za-z0-9_-]{90,})", "anthropic_key_leaked", CRITICAL, "contains an Anthropic key"),
    (r"(?-i:AKIA[0-9A-Z]{16})", "aws_access_key_leaked", CRITICAL, "contains an AWS access key"),
    (r"(?-i:glpat-[A-Za-z0-9_\-]{20,})", "gitlab_token_leaked", CRITICAL, "contains a GitLab token"),
]
_HERMES_COMPILED = [(re.compile(p, re.I), rule, sev, msg) for p, rule, sev, msg in _HERMES]

# Hermes' demotion of a bare path reference that cannot act where it sits:
# a whole-line comment in a language with comments, or a denylist literal.
_PATH_REFERENCE_RULES = frozenset({"ssh_dir_access", "aws_dir_access", "gpg_dir_access", "kube_dir_access",
                                   "docker_dir_access", "ssh_backdoor", "system_passwd_access"})
_COMMENT_PREFIX = {".py": "#", ".sh": "#", ".bash": "#", ".rb": "#", ".pl": "#", ".r": "#", ".yaml": "#",
                   ".yml": "#", ".toml": "#", ".conf": "#", ".cfg": ("#", ";"), ".ini": ("#", ";"),
                   ".js": "//", ".ts": "//", ".php": ("//", "#")}
_DENYLIST_OWNER = re.compile(
    r"^\s*(?:(?:const|let|var|export)\s+)?[\w.\-]*(?:deny|black|block|skip|exclu|ignor|forbid|refus|reject|never"
    r"|unsafe|sensitive|secret_?file|redact)[\w.\-]*\s*(?::[^=]*?)?(?:=|:\s*(?:$|[\[({]))", re.I)
_ACTION_ON_LINE = re.compile(
    r"\b(?:cat|less|more|head|tail|cp|mv|rm|scp|rsync|curl|wget|tee|chmod|chown|ssh|sudo|install|source|eval|exec"
    r"|system|popen|run|check_output|copyfile|copy2|sendfile)\b|\.(?:read|write|open|unlink|copy|append)\w*\s*\("
    r"|\bopen\s*\(|readFileSync|writeFileSync|appendFileSync|>>", re.I)

_INVISIBLE = frozenset("​‌‍⁠⁢⁣⁤﻿"
                       "‪‫‬‭‮⁦⁧⁨⁩")
# Code pushed off-screen after 200+ blanks (Hermes hidden_padded_code).
_PADDED_CODE = re.compile(r"(?<![ \t])[ \t]{200,}(?=\S[^\n]{39})")
_CODE_WORD = re.compile(r"[A-Za-z_$][\w$]{2,}")
_PROSE_SUFFIXES = {".md", ".txt", ".html", ".xml", ".tex", ".css"}
_BINARY_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".bin", ".dat", ".com", ".msi", ".dmg", ".app", ".deb", ".rpm"}


def _evidence(line: str) -> str:
    text = line.strip()
    if _LITERAL_SECRET.search(text):
        return "[REDACTED CREDENTIAL]"
    return text if len(text) <= 120 else text[:120] + "…"


def _strip_js_comments(source: str) -> str:
    """OpenClaw's comment stripper (keeps strings and line breaks)."""
    out = []
    quote = None
    escaped = False
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt in "/*":
            end = source.find("\n" if nxt == "/" else "*/", i + 2)
            after = n if end < 0 else end + (1 if nxt == "/" else 2)
            out.append(re.sub(r"[^\n]", "", source[i:after]))
            i = after
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _rule_match(rule: _Rule, source: str, lines: List[str]) -> Optional[Tuple[int, str]]:
    match = rule.pattern.search(source)
    if not match:
        return None
    if rule.context is not None and not rule.context.search(source):
        return None
    for i, line in enumerate(lines):
        if not rule.pattern.search(line):
            continue
        if rule.context is not None and rule.window is not None:
            window = "\n".join(lines[max(0, i - rule.window): i + rule.window + 1])
            if not rule.context.search(window):
                continue
        return i + 1, line
    if rule.window is not None:
        return None
    line_no = source.count("\n", 0, match.start()) + 1
    return line_no, lines[line_no - 1] if line_no - 1 < len(lines) else ""


def _benign_exec(line: str, match: re.Match, namespaces: set) -> bool:
    command = match.group(1) or match.group(2)
    idx = match.start()
    if line[idx] in "'\"":
        receiver = re.search(r"(\w+)\s*\[\s*$", line[:idx])
    elif command == "exec" and idx > 0 and line[idx - 1] == ".":
        receiver = re.search(r"(\w+)\s*$", line[: idx - 1])
    else:
        return False
    name = receiver.group(1) if receiver else None
    return not name or (name not in namespaces and name not in _CP_RECEIVERS)


def _scan_js_source(source: str, label: str) -> List[Finding]:
    findings: List[Finding] = []
    lines = source.split("\n")
    stripped = _strip_js_comments(source)
    aliases, namespaces = set(), set()
    for m in _CP_NAMED.finditer(stripped):
        for spec in (m.group(1) or m.group(2) or "").split(","):
            renamed = re.match(r"^\s*(\w+)\s+as\s+(\w+)\s*$", spec) or re.match(r"^\s*(\w+)\s*:\s*(\w+)\s*$", spec)
            if renamed and renamed.group(1) in _EXEC_METHODS:
                aliases.add(renamed.group(2))
    for m in _CP_NAMESPACE.finditer(stripped):
        namespaces.add(next(g for g in m.groups() if g))
    has_cp = "child_process" in source
    alias_res = [re.compile(rf"(?<![\w.]){re.escape(a)}\s*\(") for a in aliases]

    counts = {}

    def add(rule, severity, message, line, number):
        if counts.get(rule, 0) >= _MAX_PER_RULE:
            return
        counts[rule] = counts.get(rule, 0) + 1
        findings.append(Finding(label, number, rule, severity, message, _evidence(line)))

    for number, line in enumerate(lines, start=1):
        if has_cp:
            hit = False
            for m in _DANGEROUS_EXEC.finditer(line):
                if not _benign_exec(line, m, namespaces):
                    hit = True
            if not hit:
                hit = any(r.search(line) for r in alias_res)
            if hit:
                add("dangerous-exec", CRITICAL, "runs shell commands (child_process)", line, number)
        if _DYNAMIC_CODE.search(line):
            add("dynamic-code-execution", CRITICAL, "runs dynamically built code", line, number)
        if _CRYPTO_MINING.search(line):
            add("crypto-mining", CRITICAL, "references crypto mining", line, number)
        for m in _WEBSOCKET_PORT.finditer(line):
            if int(m.group(1)) not in _STANDARD_PORTS:
                add("suspicious-network", WARN, "WebSocket to a non-standard port", line, number)
    stripped_lines = stripped.split("\n")
    for rule in _SOURCE_RULES:
        hit = _rule_match(rule, stripped, stripped_lines)
        if hit:
            number, _ = hit
            findings.append(Finding(label, number, rule.rule, rule.severity, rule.message,
                                    _evidence(lines[number - 1] if number - 1 < len(lines) else "")))
    return findings


def _scan_skill_text(content: str, label: str) -> List[Finding]:
    findings = []
    lines = content.split("\n")
    for rule in _SKILL_TEXT_RULES:
        hit = _rule_match(rule, content, lines)
        if hit:
            number, line = hit
            evidence = "[REDACTED CREDENTIAL]" if rule.rule == "literal-secret" else _evidence(line)
            findings.append(Finding(label, number, rule.rule, rule.severity, rule.message, evidence))
    return findings


def _scan_hermes(content: str, label: str, suffix: str) -> List[Finding]:
    findings: List[Finding] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    forget_lines = mask_negated_forget("\n".join(lines)).split("\n")
    owners = _statement_owners(lines)
    comment = _COMMENT_PREFIX.get(suffix, ())
    for pattern, rule, severity, message in _HERMES_COMPILED:
        count = 0
        for i, line in enumerate(lines, start=1):
            target = forget_lines[i - 1] if rule == "forget_rules" else line
            if not pattern.search(target):
                continue
            sev = severity
            if rule in _PATH_REFERENCE_RULES:
                if comment and line.lstrip().startswith(comment):
                    continue  # Hermes: informational only
                if _DENYLIST_OWNER.match(lines[owners[i - 1]]) and not _ACTION_ON_LINE.search(line):
                    sev = WARN
            findings.append(Finding(label, i, rule, sev, message, _evidence(line)))
            count += 1
            if count >= _MAX_PER_RULE:
                break
    for i, line in enumerate(lines, start=1):
        char = next((c for c in _INVISIBLE if c in line), None)
        if char is not None:
            findings.append(Finding(label, i, "invisible_unicode", WARN,
                                    f"contains the invisible character U+{ord(char):04X}", f"U+{ord(char):04X}"))
    if suffix not in _PROSE_SUFFIXES:
        for i, line in enumerate(lines, start=1):
            m = _PADDED_CODE.search(line)
            if m and _CODE_WORD.search(line[m.end():]):
                findings.append(Finding(label, i, "hidden_padded_code", CRITICAL,
                                        "hides code after a long run of blanks", _evidence(line[m.end():])))
    return findings


_QUOTED = re.compile(r"""'[^'\n]*'|"[^"\n]*\"""")


def _statement_owners(lines: List[str]) -> List[int]:
    owners, depth, owner, continued = [], 0, 0, False
    for i, line in enumerate(lines):
        if depth <= 0 and not continued:
            owner = i
        owners.append(owner)
        bare = _QUOTED.sub("", line)
        depth = max(0, depth + sum(bare.count(c) for c in "([{") - sum(bare.count(c) for c in ")]}"))
        continued = line.rstrip().endswith("\\")
    return owners


_JS_SUFFIXES = {".js", ".ts", ".mjs", ".cjs", ".mts", ".cts", ".jsx", ".tsx"}


def scan_skill_text(content: str, label: str = "SKILL.md") -> List[Finding]:
    """Findings for one skill file's text: OpenClaw's skill-text rules, its
    JavaScript rules for JavaScript files (as its directory scan does), and
    the Hermes rules."""
    suffix = Path(label).suffix.lower()
    findings = _scan_skill_text(content, label)
    if suffix in _JS_SUFFIXES:
        findings += _scan_js_source(content, label)
    findings += _scan_hermes(content, label, suffix)
    return _dedupe(findings)


def _dedupe(findings: Iterable[Finding]) -> List[Finding]:
    seen = set()
    out = []
    for f in findings:
        key = (f.file, f.line, f.rule)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _walk(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "node_modules")
        for name in sorted(filenames):
            if not name.startswith("."):
                yield Path(dirpath) / name


def scan_skill_dir(path) -> List[Finding]:
    """Every finding in a skill folder (or a single SKILL.md), critical first."""
    root = Path(path)
    if root.is_file():
        try:
            return scan_skill_text(root.read_text(encoding="utf-8-sig", errors="replace"), root.name)
        except OSError:
            return []
    findings: List[Finding] = []
    real_root = root.resolve()
    scanned = 0
    for file in _walk(root):
        rel = file.relative_to(root).as_posix()
        findings += [f for f in _scan_skill_text(rel, "file path") if f.rule == "literal-secret"]
        if file.is_symlink():
            try:
                target = file.resolve()
            except OSError:
                continue
            if real_root not in target.parents and target != real_root:
                findings.append(Finding(rel, 0, "symlink_escape", CRITICAL,
                                        "links to a file outside the skill", ""))
            continue
        if file.suffix.lower() in _BINARY_SUFFIXES:
            findings.append(Finding(rel, 0, "binary_file", CRITICAL,
                                    f"contains a {file.suffix.lower()} program file", ""))
            continue
        if scanned >= MAX_FILES:
            break
        try:
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = file.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue  # binary data (images, archives)
        scanned += 1
        findings += scan_skill_text(raw.decode("utf-8-sig", errors="replace"), rel)
        if len(findings) >= _MAX_FINDINGS:
            break
    findings = _dedupe(findings)[:_MAX_FINDINGS]
    return sorted(findings, key=lambda f: (f.severity != CRITICAL, f.file, f.line))


def describe(findings: List[Finding], limit: int = 5) -> str:
    """A short list for a message: "SKILL.md:12 pipes a download into a shell"."""
    parts = []
    for f in findings[:limit]:
        where = f"{f.file}:{f.line}" if f.line else f.file
        parts.append(f"{where} {f.message} ({f.rule})")
    more = len(findings) - limit
    text = "; ".join(parts)
    return text + (f"; and {more} more" if more > 0 else "")


def install_check(path, *, source: str = "") -> Tuple[Optional[str], str]:
    """(refusal, note) for installing the skill folder at ``path``.

    Both are empty unless Settings > Security > Scan skills is on. A
    critical finding refuses the install; warnings let it proceed and are
    returned as a note to add to the success message.
    """
    from app.security.policy import get_policy

    if not get_policy().scan_skills:
        return None, ""
    return _verdict(scan_skill_dir(path), source or str(path))


def text_check(content: str, *, label: str = "SKILL.md", source: str = "") -> Tuple[Optional[str], str]:
    """``install_check`` for one skill file's text before it is written."""
    from app.security.policy import get_policy

    if not get_policy().scan_skills:
        return None, ""
    return _verdict(scan_skill_text(content, label), source or label)


def _verdict(findings: List[Finding], source: str) -> Tuple[Optional[str], str]:
    critical = [f for f in findings if f.severity == CRITICAL]
    if critical:
        try:
            from app.security import audit

            audit.record("skill_blocked", source=source, rules=sorted({f.rule for f in critical}))
        except Exception:
            pass
        return f"Not installed: the security scan found {describe(critical)}.", ""
    if findings:
        return None, f" Security scan warnings: {describe(findings)}."
    return None, ""
