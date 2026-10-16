from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

from locallens.security.redaction import has_secret_text


WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/)[^\s\"']+")
POSIX_ABSOLUTE_PATH = re.compile(r"(?<![\w:])/(?:home|users|var|tmp|etc)/[^\s\"']+")
TEXT_ARTIFACT_SUFFIXES = {
    ".example",
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".tsv",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_ARTIFACT_NAMES = {".gitignore"}
BINARY_ARTIFACT_SUFFIXES = {".jpg", ".jpeg", ".pdf", ".png"}


@dataclass(frozen=True)
class ArtifactFinding:
    path: str
    reason: str
    rule_id: str


def load_blocked_terms(
    terms: list[str] | None = None,
    terms_file: str | Path | None = None,
) -> list[str]:
    result = list(terms or [])
    if terms_file:
        result.extend(
            line.strip()
            for line in Path(terms_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return result


def public_findings(findings: list[ArtifactFinding]) -> list[dict]:
    return [
        {
            "path": public_path_label(finding.path, finding.rule_id),
            "reason": finding.reason,
            "rule_id": finding.rule_id,
        }
        for finding in findings
    ]


def public_path_label(raw_path: str, rule_id: str = "") -> str:
    if rule_id.startswith("blocked-expression-path-"):
        return "<blocked-path>"
    path = Path(raw_path)
    if not path.is_absolute():
        return raw_path
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return f"<external>/{path.name}"


def scan_artifacts(paths: list[Path], banned_terms: list[str]) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    for path in paths:
        findings.extend(
            _scan_blocked_terms(path.as_posix(), path.as_posix(), banned_terms, "path")
        )
        if is_text_artifact(path):
            text = path.read_text(encoding="utf-8", errors="ignore")
            findings.extend(scan_text_artifact(text, path.as_posix(), banned_terms))
        elif is_binary_artifact(path):
            text = _binary_artifact_text(path)
            if text:
                findings.extend(scan_text_artifact(text, path.as_posix(), banned_terms))
    return findings


def scan_text_artifact(
    text: str, artifact_name: str, banned_terms: list[str]
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    findings.extend(_scan_blocked_terms(text, artifact_name, banned_terms, "content"))
    if has_secret_text(text):
        findings.append(ArtifactFinding(artifact_name, "secret-like content", "secret"))
    if WINDOWS_ABSOLUTE_PATH.search(text) or POSIX_ABSOLUTE_PATH.search(text):
        findings.append(ArtifactFinding(artifact_name, "absolute path", "absolute-path"))
    return findings


def _scan_blocked_terms(
    text: str, artifact_name: str, banned_terms: list[str], surface: str
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    for index, term in enumerate([term.lower() for term in banned_terms], start=1):
        if term and _matches_blocked_term(text, term):
            findings.append(
                ArtifactFinding(
                    artifact_name,
                    "blocked expression",
                    f"blocked-expression-{surface}-{index:03d}",
                )
            )
    return findings


def _matches_blocked_term(text: str, term: str) -> bool:
    normalized_term = _normalize_for_blocked_terms(term)
    normalized_text = _normalize_for_blocked_terms(text)
    if not normalized_term:
        return False
    if " " in normalized_term:
        pattern = rf"(?<![A-Za-z0-9가-힣]){re.escape(normalized_term)}(?![A-Za-z0-9가-힣])"
        return bool(re.search(pattern, normalized_text))
    pattern = rf"(?<![A-Za-z0-9가-힣]){re.escape(normalized_term)}(?![A-Za-z0-9가-힣])"
    return bool(re.search(pattern, normalized_text))


def _normalize_for_blocked_terms(text: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", text.lower()).strip()


def is_text_artifact(path: Path) -> bool:
    return path.name in TEXT_ARTIFACT_NAMES or path.suffix.lower() in TEXT_ARTIFACT_SUFFIXES


def is_binary_artifact(path: Path) -> bool:
    return path.suffix.lower() in BINARY_ARTIFACT_SUFFIXES


def _binary_artifact_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_artifact_text(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return _image_artifact_text(path)
    return ""


def _pdf_artifact_text(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    previous_error_display = None
    previous_warning_display = None
    try:
        previous_error_display = fitz.TOOLS.mupdf_display_errors()
        previous_warning_display = fitz.TOOLS.mupdf_display_warnings()
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            with fitz.open(path) as doc:
                metadata = "\n".join(str(value or "") for value in doc.metadata.values())
                pages = "\n".join((page.get_text() or "") for page in doc)
            return f"{metadata}\n{pages}"
    except Exception:
        return ""
    finally:
        if previous_error_display is not None:
            fitz.TOOLS.mupdf_display_errors(previous_error_display)
        if previous_warning_display is not None:
            fitz.TOOLS.mupdf_display_warnings(previous_warning_display)


def _image_artifact_text(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError:
        return ""
    try:
        with Image.open(path) as image:
            parts = [f"{key}: {value}" for key, value in image.info.items()]
            try:
                exif = image.getexif()
                parts.extend(f"{key}: {value}" for key, value in exif.items())
            except Exception:
                pass
            return "\n".join(parts)
    except Exception:
        return ""
