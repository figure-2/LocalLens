from __future__ import annotations

from PIL import Image, PngImagePlugin

from locallens.security.artifact_scan import (
    load_blocked_terms,
    public_findings,
    scan_artifacts,
    scan_text_artifact,
)
from locallens.security.redaction import redact_secret_text


def test_public_artifact_scan_flags_secret_and_absolute_path(tmp_path):
    report = tmp_path / "report.json"
    key_name = "to" + "ken"
    key_value = "abc" + "123456789"
    absolute_path = "C:" + "\\Users\\name\\secret.txt"
    report.write_text(
        '{"'
        + key_name
        + '":"'
        + key_value
        + '","path":"'
        + absolute_path.replace("\\", "\\\\")
        + '"}',
        encoding="utf-8",
    )

    findings = scan_artifacts([report], banned_terms=[])

    assert {finding.reason for finding in findings} == {
        "secret-like content",
        "absolute path",
    }


def test_public_artifact_scan_flags_forward_slash_windows_path():
    absolute_path = "C:" + "/Users/name/secret.txt"
    findings = scan_text_artifact(
        '{"path":"' + absolute_path + '"}',
        "report.json",
        banned_terms=[],
    )

    assert {finding.reason for finding in findings} == {"absolute path"}


def test_artifact_scan_checks_csv_tsv_and_log_failure_artifacts(tmp_path):
    absolute_path = "C:" + "\\Users\\name\\cache.bin"
    artifacts = [
        tmp_path / "failure.csv",
        tmp_path / "failure.tsv",
        tmp_path / "failure.log",
    ]
    for artifact in artifacts:
        artifact.write_text(f"case,path\n1,{absolute_path}\n", encoding="utf-8")

    findings = scan_artifacts(artifacts, banned_terms=[])

    assert len(findings) == 3
    assert {finding.reason for finding in findings} == {"absolute path"}


def test_secret_scan_and_redaction_handle_compound_key_names():
    first_sample = "OPENAI_" + "API_KEY=sk-" + "abcdef123456"
    second_sample = "access_" + "token: tok_" + "abcdef123456"
    text = (
        f"{first_sample} "
        f"{second_sample} "
        f"{'client_' + 'secret=sec_' + 'abcdef123456'} "
        f"{'db_' + 'password=pw_' + 'abcdef123456'}"
    )

    redacted = redact_secret_text(text)
    findings = scan_text_artifact(text, "report.json", banned_terms=[])

    assert "sk-" + "abcdef123456" not in redacted
    assert "tok_" + "abcdef123456" not in redacted
    assert "sec_" + "abcdef123456" not in redacted
    assert "pw_" + "abcdef123456" not in redacted
    assert findings


def test_secret_scan_and_redaction_handle_common_leak_shapes():
    begin = "-----BEGIN " + "PRIVATE KEY-----"
    end = "-----END " + "PRIVATE KEY-----"
    bearer = "Authorization: " + "Bearer " + "abcdef1234567890abcdef"
    session_id = "session" + "_id=sess_" + "abcdef1234567890"
    url = "https://" + "user:password123" + "@example.test/path"
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9."
        + "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        + "abcdef1234567890"
    )
    text = "\n".join(
        [
            bearer,
            session_id,
            url,
            jwt,
            f"{begin}\nabc123456789\n{end}",
        ]
    )

    redacted = redact_secret_text(text)
    findings = scan_text_artifact(text, "report.json", banned_terms=[])

    assert "abcdef1234567890" + "abcdef" not in redacted
    assert "sess_" + "abcdef1234567890" not in redacted
    assert "user:" + "password123" not in redacted
    assert "eyJhbGci" not in redacted
    assert begin.replace("-----", "") not in redacted
    assert {finding.reason for finding in findings} == {"secret-like content"}


def test_artifact_scan_accepts_external_blocked_terms():
    findings = scan_text_artifact(
        "release checkpoint marker",
        "report.json",
        banned_terms=["checkpoint marker"],
    )

    assert len(findings) == 1
    assert findings[0].reason == "blocked expression"
    assert "checkpoint marker" not in findings[0].reason


def test_load_blocked_terms_reads_external_file(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("\n# comment\nrelease marker\n\nextra marker\n", encoding="utf-8")

    assert load_blocked_terms(["inline marker"], terms) == [
        "inline marker",
        "release marker",
        "extra marker",
    ]


def test_artifact_scan_uses_token_boundaries_for_short_terms():
    clean_findings = scan_text_artifact(
        "prefixed indexed mixed",
        "report.json",
        banned_terms=["xid"],
    )
    blocked_findings = scan_text_artifact(
        "open xid for local service",
        "report.json",
        banned_terms=["xid"],
    )

    assert clean_findings == []
    assert len(blocked_findings) == 1
    assert blocked_findings[0].reason == "blocked expression"


def test_artifact_scan_checks_file_names_without_echoing_terms(tmp_path):
    path = tmp_path / "release-checkpoint-marker.md"
    path.write_text("clean body", encoding="utf-8")

    findings = scan_artifacts([path], banned_terms=["checkpoint marker"])

    assert len(findings) == 1
    assert findings[0].reason == "blocked expression"
    assert findings[0].rule_id.startswith("blocked-expression-path-")


def test_public_findings_sanitizes_absolute_and_blocked_paths(tmp_path):
    absolute = tmp_path / "release-checkpoint-marker.md"
    absolute.write_text("clean body", encoding="utf-8")
    findings = scan_artifacts([absolute], banned_terms=["checkpoint marker"])

    public = public_findings(findings)

    assert public == [
        {
            "path": "<blocked-path>",
            "reason": "blocked expression",
            "rule_id": findings[0].rule_id,
        }
    ]
    assert str(tmp_path) not in str(public)


def test_artifact_scan_checks_png_metadata(tmp_path):
    path = tmp_path / "image.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Description", "release marker")
    Image.new("RGB", (4, 4), "white").save(path, pnginfo=metadata)

    findings = scan_artifacts([path], banned_terms=["release marker"])

    assert len(findings) == 1
    assert findings[0].reason == "blocked expression"


def test_artifact_scan_checks_pdf_text(tmp_path):
    fitz = __import__("fitz")
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((24, 48), "release marker")
    doc.save(str(path))
    doc.close()

    findings = scan_artifacts([path], banned_terms=["release marker"])

    assert len(findings) == 1
    assert findings[0].reason == "blocked expression"
