from pathlib import Path

from scripts import release_secret_scan


def _write_payload_file(scan_root: Path, rel_path: str, text: str) -> Path:
    target = scan_root / Path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_detect_secrets_line_allowlist_matches_reviewed_keyword_false_positives(
    tmp_path: Path,
) -> None:
    scan_root = tmp_path / "payload"
    _write_payload_file(
        scan_root,
        "_internal/keyring-25.7.0.dist-info/entry_points.txt",
        "SecretService = keyring.backends.SecretService\n"
        "libsecret = keyring.backends.libsecret\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/literature_assistant/core/credential_store.py",
        'SECRET_REF_FIELD = "api_key_secret_ref"\n'
        'SECRET_BACKEND_ENV = "LITASSIST_CREDENTIAL_SECRET_BACKEND"\n'
        '                    "api_key_secret_ref": "keyring:cred_...:...:api_key"\n',
    )
    _write_payload_file(
        scan_root,
        "_internal/literature_assistant/core/model_config_store.py",
        'MODEL_OVERRIDE_SECRET_REF_FIELD = "api_key_secret_ref"\n',
    )
    _write_payload_file(
        scan_root,
        "_internal/_tcl_data/encoding/cp874.enc",
        "20AC008100820083008420260086008700880089008A008B008C008D008E008F\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/_tcl_data/encoding/cp936.enc",
        "20AC000000000000000000000000000000000000000000000000000000000000\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/_tcl_data/encoding/cp949.enc",
        "0000CAA8CAA9CAAACAABCAACCAADCAAECAAFCAB0CAB1CAB2CAB3CAB4CAB5CAB6\n"
        "CCA7CCAACCAECCAFCCB0CCB1CCB2CCB3CCB6CCB7CCB900000000000000000000\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/_tcl_data/encoding/cp950.enc",
        "000020AC00000000000000000000000000000000000000000000000000000000\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/tcl8/8.6/http-2.9.8.tm",
        "#     http://jschmoe:xyzzy@www.bogus.net:8000/foo/bar.tml?q=foo#changes\n",
    )

    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/keyring-25.7.0.dist-info/entry_points.txt",
        "Secret Keyword",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/keyring-25.7.0.dist-info/entry_points.txt",
        "Secret Keyword",
        2,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        2,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        3,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/literature_assistant/core/model_config_store.py",
        "Secret Keyword",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp874.enc",
        "Twilio API Key",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp936.enc",
        "Twilio API Key",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp949.enc",
        "AWS Access Key",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp949.enc",
        "AWS Access Key",
        2,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp950.enc",
        "Twilio API Key",
        1,
        scan_root,
    )
    assert release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/tcl8/8.6/http-2.9.8.tm",
        "Basic Auth Credentials",
        1,
        scan_root,
    )


def test_detect_secrets_line_allowlist_does_not_hide_real_secret_shapes(
    tmp_path: Path,
) -> None:
    scan_root = tmp_path / "payload"
    _write_payload_file(
        scan_root,
        "_internal/literature_assistant/core/credential_store.py",
        'OPENAI_API_KEY = "sk-testvalue-that-is-long-enough-to-block"\n',
    )

    assert not release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/literature_assistant/core/credential_store.py",
        "Secret Keyword",
        1,
        scan_root,
    )
    findings = release_secret_scan.run_custom_regex_scan(scan_root)
    assert findings
    assert findings[0]["rule_id"] == "custom_regex:env_var_api_key"


def test_detect_secrets_line_allowlist_requires_exact_tcl_false_positive_lines(
    tmp_path: Path,
) -> None:
    scan_root = tmp_path / "payload"
    _write_payload_file(
        scan_root,
        "_internal/_tcl_data/encoding/cp874.enc",
        "20AC008100820083008420260086008700880089008A008B008C008D008E0080\n",
    )
    _write_payload_file(
        scan_root,
        "_internal/tcl8/8.6/http-2.9.8.tm",
        "#     http://admin:actual-password@example.com:8000/foo/bar.tml?q=foo#changes\n",
    )

    assert not release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/_tcl_data/encoding/cp874.enc",
        "Twilio API Key",
        1,
        scan_root,
    )
    assert not release_secret_scan.is_detect_secrets_line_allowlisted(
        "_internal/tcl8/8.6/http-2.9.8.tm",
        "Basic Auth Credentials",
        1,
        scan_root,
    )
