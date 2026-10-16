from __future__ import annotations

import re


REDACTION_TEXT = "[REDACTED]"
SENSITIVE_KEY_PATTERN = (
    r"[A-Za-z0-9_-]*"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"secret|token|password)"
    r"[A-Za-z0-9_-]*"
)
ASSIGNMENT_PATTERN = re.compile(
    rf"(?i)(?<![A-Za-z0-9])['\"]?({SENSITIVE_KEY_PATTERN})['\"]?\s*[:=]\s*['\"]?([^\s'\",;}}{{]{{6,}})"
)
BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]{12,})")
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
URL_CREDENTIALS = re.compile(r"\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s:@]+)@")
HEADER_COOKIE_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|cookie|session(?:[_-]?id)?)\b\s*[:=]\s*)([^\s;,\"]{8,})"
)

SENSITIVE_PATTERNS = (
    ASSIGNMENT_PATTERN,
    BEARER_PATTERN,
    JWT_PATTERN,
    PRIVATE_KEY_PATTERN,
    URL_CREDENTIALS,
    HEADER_COOKIE_PATTERN,
)


def redact_secret_text(text: str) -> str:
    text = ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTION_TEXT}",
        text,
    )
    text = BEARER_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTION_TEXT}", text)
    text = JWT_PATTERN.sub(REDACTION_TEXT, text)
    text = PRIVATE_KEY_PATTERN.sub(REDACTION_TEXT, text)
    text = URL_CREDENTIALS.sub(
        lambda match: f"{match.group(1)}{REDACTION_TEXT}@",
        text,
    )
    return HEADER_COOKIE_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTION_TEXT}",
        text,
    )


def has_secret_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)
