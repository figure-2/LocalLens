from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from locallens.security.artifact_manifest import ManifestEntryError
from locallens.security.artifact_manifest import artifact_paths_from_manifest
from locallens.security.artifact_manifest import manifest_entries


@dataclass(frozen=True)
class EvidenceFinding:
    reason: str
    artifact: str
    check_id: str
    detail: str


def check_evidence_consistency(
    *,
    root: Path,
    claims_file: str | Path = "release_evidence_claims.json",
    generated_manifest: str | Path = "generated_evidence_artifacts.txt",
    publication_manifests: list[str | Path] | None = None,
) -> dict:
    claims_path = _resolve(root, claims_file)
    manifest_path = _resolve(root, generated_manifest)
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    findings: list[EvidenceFinding] = []
    manifest_entries_set = _safe_manifest_entries(
        manifest_path, root=root, findings=findings, check_id="generated-manifest"
    )

    _check_required_artifacts(claims, manifest_entries_set, findings)
    _check_historical_artifacts(claims, manifest_entries_set, findings)
    _check_publication_references(
        claims,
        root=root,
        publication_manifests=publication_manifests or claims.get(
            "publication_manifests", ["publication_artifacts.txt"]
        ),
        findings=findings,
    )
    _check_public_metric_table_coverage(claims, root, findings)
    _check_claim_values(claims, root, findings)
    _check_semantic_text_guards(claims, root, findings)

    return {
        "status": "failed" if findings else "passed",
        "claims_file": _relative_label(root, claims_path),
        "generated_manifest": _relative_label(root, manifest_path),
        "checked_claims": len(claims.get("checks", [])),
        "checked_public_metric_table_cells": _public_metric_table_cell_count(
            claims, root
        ),
        "checked_public_text_assertions": sum(
            len(check.get("public_text", [])) for check in claims.get("checks", [])
        ),
        "checked_public_table_assertions": sum(
            len(check.get("public_table", [])) for check in claims.get("checks", [])
        ),
        "checked_semantic_text_guards": len(claims.get("semantic_text_guards", [])),
        "findings": [asdict(item) for item in findings],
    }


def _check_required_artifacts(
    claims: dict, manifest_entries: set[str], findings: list[EvidenceFinding]
) -> None:
    for artifact in claims.get("required_artifacts", []):
        if artifact not in manifest_entries:
            findings.append(
                EvidenceFinding(
                    reason="required artifact missing from generated manifest",
                    artifact=artifact,
                    check_id="required-artifacts",
                    detail="current release evidence must be listed explicitly",
                )
            )


def _check_historical_artifacts(
    claims: dict, manifest_entries: set[str], findings: list[EvidenceFinding]
) -> None:
    for artifact in claims.get("historical_artifacts", []):
        if artifact in manifest_entries:
            findings.append(
                EvidenceFinding(
                    reason="historical artifact listed as current evidence",
                    artifact=artifact,
                    check_id="historical-artifacts",
                    detail="older reports cannot support current claims",
                )
            )


def _check_publication_references(
    claims: dict,
    *,
    root: Path,
    publication_manifests: list[str | Path],
    findings: list[EvidenceFinding],
) -> None:
    historical = set(claims.get("historical_artifacts", []))
    if not historical:
        return
    public_paths: list[Path] = []
    for manifest in publication_manifests:
        public_paths.extend(
            _safe_artifact_paths_from_manifest(
                _resolve(root, manifest),
                root=root,
                findings=findings,
                check_id="publication-manifest",
            )
        )
    for path in public_paths:
        if not path.is_file():
            continue
        if path.name == "release_evidence_claims.json":
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".toml", ".example"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for artifact in historical:
            if artifact in text or artifact.replace("/", "\\") in text:
                findings.append(
                    EvidenceFinding(
                        reason="historical artifact referenced by publication surface",
                        artifact=_relative_label(root, path),
                        check_id="publication-historical-reference",
                        detail=artifact,
                    )
                )


def _check_public_metric_table_coverage(
    claims: dict,
    root: Path,
    findings: list[EvidenceFinding],
) -> None:
    covered = _public_table_assertion_keys(claims)
    for target in claims.get("public_metric_table_coverage", []):
        artifact = str(target["artifact"])
        scope_key = _table_scope_key(target.get("required_headers", []))
        path = _resolve(root, artifact)
        if not path.exists():
            findings.append(
                EvidenceFinding(
                    reason="public metric table artifact missing",
                    artifact=artifact,
                    check_id="public-metric-table-coverage",
                    detail="required public metric table target is absent",
                )
            )
            continue
        for cell_scope_key, row_key, column, cell in _public_metric_table_cells(
            path.read_text(encoding="utf-8", errors="ignore"),
            required_headers=target.get("required_headers", []),
            columns=target.get("columns", []),
            single_number_only=bool(target.get("single_number_only", False)),
        ):
            key = (
                artifact,
                cell_scope_key or scope_key,
                _normalize_table_cell(row_key),
                _normalize_table_cell(column),
            )
            wildcard_key = (
                artifact,
                "*",
                _normalize_table_cell(row_key),
                _normalize_table_cell(column),
            )
            if key in covered or wildcard_key in covered:
                continue
            findings.append(
                EvidenceFinding(
                    reason="public metric table cell missing claim",
                    artifact=artifact,
                    check_id="public-metric-table-coverage",
                    detail=f"row={row_key} column={column} cell={cell}",
                )
            )


def _check_claim_values(claims: dict, root: Path, findings: list[EvidenceFinding]) -> None:
    cache: dict[str, Any] = {}
    for check in claims.get("checks", []):
        artifact = str(check["artifact"])
        if artifact not in cache:
            report_path = _resolve(root, artifact)
            if not report_path.exists():
                findings.append(
                    EvidenceFinding(
                        reason="claim artifact missing on disk",
                        artifact=artifact,
                        check_id=str(check.get("id", "unnamed-check")),
                        detail="run or refresh the required evidence report",
                    )
                )
                continue
            cache[artifact] = json.loads(report_path.read_text(encoding="utf-8"))
        try:
            value = _json_path(cache[artifact], str(check["path"]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            findings.append(
                EvidenceFinding(
                    reason="claim path not found",
                    artifact=artifact,
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=str(exc),
                )
            )
            continue
        finding = _compare_claim(check, value)
        if finding:
            findings.append(
                EvidenceFinding(
                    reason=finding,
                    artifact=artifact,
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=f"path={check['path']}",
                )
            )
            continue
        _check_public_text_assertions(check, value, root, findings)
        _check_public_table_assertions(check, value, root, findings)


def _check_public_text_assertions(
    check: dict,
    value: Any,
    root: Path,
    findings: list[EvidenceFinding],
) -> None:
    for assertion in check.get("public_text", []):
        path = _resolve(root, assertion["artifact"])
        if not path.exists():
            findings.append(
                EvidenceFinding(
                    reason="public assertion artifact missing",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail="required public text target is absent",
                )
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        expected = _public_assertion_text(assertion, value)
        if expected not in text:
            findings.append(
                EvidenceFinding(
                    reason="public claim text mismatch",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=expected,
                )
            )


def _check_public_table_assertions(
    check: dict,
    value: Any,
    root: Path,
    findings: list[EvidenceFinding],
) -> None:
    for assertion in check.get("public_table", []):
        path = _resolve(root, assertion["artifact"])
        if not path.exists():
            findings.append(
                EvidenceFinding(
                    reason="public table artifact missing",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail="required public table target is absent",
                )
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        expected = _public_assertion_text(assertion, value)
        cells = _public_table_cells(
            text,
            row_key=str(assertion["row_key"]),
            column=str(assertion["column"]),
            match_column=assertion.get("match_column"),
            required_headers=assertion.get("required_headers", []),
        )
        if not cells:
            findings.append(
                EvidenceFinding(
                    reason="public table cell not found",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=f"row={assertion['row_key']} column={assertion['column']}",
                )
            )
            continue
        if len(cells) > 1:
            findings.append(
                EvidenceFinding(
                    reason="public table row is ambiguous",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=f"row={assertion['row_key']} column={assertion['column']}",
                )
            )
            continue
        cell = cells[0]
        if assertion.get("exact"):
            if _normalize_table_cell(cell) == _normalize_table_cell(expected):
                continue
            findings.append(
                EvidenceFinding(
                    reason="public table claim mismatch",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=expected,
                )
            )
            continue
        if expected not in cell:
            findings.append(
                EvidenceFinding(
                    reason="public table claim mismatch",
                    artifact=str(assertion["artifact"]),
                    check_id=str(check.get("id", "unnamed-check")),
                    detail=expected,
                )
            )


def _check_semantic_text_guards(
    claims: dict,
    root: Path,
    findings: list[EvidenceFinding],
) -> None:
    cache: dict[str, Any] = {}
    for guard in claims.get("semantic_text_guards", []):
        guard_id = str(guard.get("id", "unnamed-semantic-guard"))
        artifact = str(guard["artifact"])
        if artifact not in cache:
            report_path = _resolve(root, artifact)
            if not report_path.exists():
                findings.append(
                    EvidenceFinding(
                        reason="semantic guard artifact missing on disk",
                        artifact=artifact,
                        check_id=guard_id,
                        detail="run or refresh the required evidence report",
                    )
                )
                continue
            cache[artifact] = json.loads(report_path.read_text(encoding="utf-8"))
        try:
            value = _json_path(cache[artifact], str(guard["path"]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            findings.append(
                EvidenceFinding(
                    reason="semantic guard path not found",
                    artifact=artifact,
                    check_id=guard_id,
                    detail=str(exc),
                )
            )
            continue
        active_when = guard.get("active_when", {"equals": True})
        if _compare_claim(active_when, value) is not None:
            continue
        _check_guarded_public_text(guard, root, findings)


def _check_guarded_public_text(
    guard: dict,
    root: Path,
    findings: list[EvidenceFinding],
) -> None:
    guard_id = str(guard.get("id", "unnamed-semantic-guard"))
    blocked_patterns = [re.compile(item, re.IGNORECASE) for item in guard["blocked_patterns"]]
    allowed_patterns = [
        re.compile(item, re.IGNORECASE) for item in guard.get("allowed_line_patterns", [])
    ]
    for artifact in guard.get("scan_artifacts", []):
        paths = _semantic_guard_paths(root, str(artifact))
        if not paths:
            findings.append(
                EvidenceFinding(
                    reason="semantic guard target missing",
                    artifact=str(artifact),
                    check_id=guard_id,
                    detail="required semantic scan target is absent",
                )
            )
            continue
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for pattern in blocked_patterns:
                    if not pattern.search(line):
                        continue
                    if any(allowed.search(line) for allowed in allowed_patterns):
                        continue
                    findings.append(
                        EvidenceFinding(
                            reason="semantic claim guard violation",
                            artifact=_relative_label(root, path),
                            check_id=guard_id,
                            detail=f"line={line_no} pattern={pattern.pattern}",
                        )
                    )


def _semantic_guard_paths(root: Path, artifact: str) -> list[Path]:
    path = _resolve(root, artifact)
    if path.is_file():
        return [path]
    if path.is_dir():
        return [
            item
            for item in path.rglob("*")
            if item.is_file() and item.suffix.lower() in {".md", ".txt", ".json"}
        ]
    return []


def _public_assertion_text(assertion: dict, value: Any) -> str:
    if "contains" in assertion:
        return str(assertion["contains"])
    value_format = assertion.get("value_format")
    if value_format:
        value_text = format(float(value), value_format)
    else:
        value_text = str(value)
    template = assertion.get("template", "{value}")
    return template.replace("{value}", value_text)


def _public_table_cells(
    text: str,
    *,
    row_key: str,
    column: str,
    match_column: str | None = None,
    required_headers: list[str] | None = None,
) -> list[str]:
    wanted_column = _normalize_table_cell(column)
    wanted_match_column = _normalize_table_cell(match_column or "")
    wanted_row = _normalize_table_cell(row_key)
    wanted_headers = {_normalize_table_cell(item) for item in required_headers or []}
    cells: list[str] = []
    for table in _markdown_tables(text):
        headers = table["headers"]
        normalized_headers = {_normalize_table_cell(item) for item in headers}
        if wanted_headers and not wanted_headers.issubset(normalized_headers):
            continue
        rows = table["rows"]
        column_index = _table_column_index(headers, wanted_column)
        if column_index is None:
            continue
        match_index = 0 if not wanted_match_column else _table_column_index(
            headers,
            wanted_match_column,
        )
        if match_index is None:
            continue
        for row in rows:
            if len(row) <= max(column_index, match_index):
                continue
            if _normalize_table_cell(row[match_index]) == wanted_row:
                cells.append(row[column_index])
    return cells


def _public_metric_table_cell_count(claims: dict, root: Path) -> int:
    total = 0
    for target in claims.get("public_metric_table_coverage", []):
        path = _resolve(root, target["artifact"])
        if not path.exists():
            continue
        total += len(
            _public_metric_table_cells(
                path.read_text(encoding="utf-8", errors="ignore"),
                required_headers=target.get("required_headers", []),
                columns=target.get("columns", []),
                single_number_only=bool(target.get("single_number_only", False)),
            )
        )
    return total


def _public_table_assertion_keys(claims: dict) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for check in claims.get("checks", []):
        for assertion in check.get("public_table", []):
            scope_key = _table_scope_key(assertion.get("required_headers", []))
            keys.add(
                (
                    str(assertion["artifact"]),
                    scope_key,
                    _normalize_table_cell(str(assertion["row_key"])),
                    _normalize_table_cell(str(assertion["column"])),
                )
            )
    return keys


def _public_metric_table_cells(
    text: str,
    *,
    required_headers: list[str],
    columns: list[str],
    single_number_only: bool = False,
) -> list[tuple[str, str, str, str]]:
    wanted_headers = {_normalize_table_cell(item) for item in required_headers}
    wanted_columns = {_normalize_table_cell(item) for item in columns}
    scope_key = _table_scope_key(required_headers)
    cells: list[tuple[str, str, str, str]] = []
    for table in _markdown_tables(text):
        headers = table["headers"]
        normalized_headers = {_normalize_table_cell(item) for item in headers}
        if wanted_headers and not wanted_headers.issubset(normalized_headers):
            continue
        column_indexes = [
            (index, headers[index])
            for index in range(len(headers))
            if _normalize_table_cell(headers[index]) in wanted_columns
        ]
        for row in table["rows"]:
            if not row:
                continue
            row_key = row[0]
            for index, column in column_indexes:
                if len(row) <= index:
                    continue
                cell = row[index]
                if single_number_only and _number_token_count(cell) != 1:
                    continue
                if _contains_number(cell):
                    cells.append((scope_key, row_key, column, cell))
    return cells


def _markdown_tables(text: str) -> list[dict[str, list[list[str]] | list[str]]]:
    lines = text.splitlines()
    tables = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_table_row(line) or index + 1 >= len(lines):
            index += 1
            continue
        separator = lines[index + 1]
        if not _is_table_separator(separator):
            index += 1
            continue
        headers = _split_table_row(line)
        rows = []
        index += 2
        while index < len(lines) and _is_table_row(lines[index]):
            rows.append(_split_table_row(lines[index]))
            index += 1
        tables.append({"headers": headers, "rows": rows})
    return tables


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_column_index(headers: list[str], column: str) -> int | None:
    for index, header in enumerate(headers):
        if _normalize_table_cell(header) == column:
            return index
    return None


def _normalize_table_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "").strip())


def _table_scope_key(required_headers: list[str] | None) -> str:
    if not required_headers:
        return "*"
    return "|".join(sorted(_normalize_table_cell(item) for item in required_headers))


def _contains_number(value: str) -> bool:
    return bool(re.search(r"\d", value))


def _number_token_count(value: str) -> int:
    return len(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:k)?", value))


def _compare_claim(check: dict, value: Any) -> str | None:
    if "equals" in check and value != check["equals"]:
        return "claim value mismatch"
    if "approx_equals" in check:
        tolerance = float(check.get("tolerance", 1e-6))
        if abs(float(value) - float(check["approx_equals"])) > tolerance:
            return "claim value outside tolerance"
    if "minimum" in check and float(value) < float(check["minimum"]):
        return "claim value below minimum"
    if "maximum" in check and float(value) > float(check["maximum"]):
        return "claim value above maximum"
    if "contains" in check and check["contains"] not in value:
        return "claim list does not contain required value"
    return None


def _json_path(data: Any, path: str) -> Any:
    current = data
    for raw_token in path.split("."):
        match = re.fullmatch(r"([A-Za-z0-9_]+)(?:\[(.+)\])?", raw_token)
        if not match:
            raise ValueError(f"unsupported path token: {raw_token}")
        key, selector = match.groups()
        current = current[key]
        if selector is None:
            continue
        if selector.isdigit():
            current = current[int(selector)]
            continue
        if "=" not in selector:
            raise ValueError(f"unsupported list selector: {selector}")
        field, expected = selector.split("=", maxsplit=1)
        current = _select_list_item(current, field, expected)
    return current


def _select_list_item(items: Any, field: str, expected: str) -> Any:
    if not isinstance(items, list):
        raise TypeError(f"selector requires a list for {field}")
    for item in items:
        if str(item.get(field)) == expected:
            return item
    raise KeyError(f"no list item where {field}={expected}")


def _safe_artifact_paths_from_manifest(
    manifest: Path,
    *,
    root: Path,
    findings: list[EvidenceFinding],
    check_id: str,
) -> list[Path]:
    try:
        paths = artifact_paths_from_manifest(manifest)
    except ManifestEntryError as exc:
        _append_manifest_finding(exc, root=root, findings=findings, check_id=check_id)
        return []
    resolved_paths: list[Path] = []
    for resolved in paths:
        if resolved.is_dir():
            resolved_paths.extend(item for item in resolved.rglob("*") if item.is_file())
        else:
            resolved_paths.append(resolved)
    return resolved_paths


def _safe_manifest_entries(
    manifest: Path,
    *,
    root: Path,
    findings: list[EvidenceFinding],
    check_id: str,
) -> set[str]:
    try:
        return manifest_entries(manifest)
    except ManifestEntryError as exc:
        _append_manifest_finding(exc, root=root, findings=findings, check_id=check_id)
        return set()


def _append_manifest_finding(
    exc: ManifestEntryError,
    *,
    root: Path,
    findings: list[EvidenceFinding],
    check_id: str,
) -> None:
    findings.append(
        EvidenceFinding(
            reason="unsafe artifact manifest entry",
            artifact=_relative_label(root, exc.manifest),
            check_id=check_id,
            detail=f"line={exc.line_no} reason={exc.reason}",
        )
    )


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _relative_label(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
