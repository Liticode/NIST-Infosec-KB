from pathlib import Path

import pytest

from atlas.cli import main
from atlas.config import settings
from atlas.fetch import assert_allowed_url, resolve_local, resolve_redirect


def test_allowlist_rejects_unknown_host():
    with pytest.raises(ValueError, match="allowlist"):
        assert_allowed_url("https://evil.example/catalog.json")


def test_allowlist_rejects_http():
    with pytest.raises(ValueError, match="https"):
        assert_allowed_url("http://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")


def test_allowlist_accepts_nist_github_and_cisa():
    assert_allowed_url(
        "https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog-min.json"
    )
    assert_allowed_url("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")
    assert_allowed_url(
        "https://csrc.nist.gov/extensions/nudp/services/json/nudp/framework/version/SP800_66_2_0_0/export/json?element=all"
    )


def test_redirect_must_stay_https_and_allowlisted():
    nxt = resolve_redirect("https://www.cisa.gov/a", "/b")
    assert nxt.startswith("https://www.cisa.gov/")
    with pytest.raises(ValueError, match="https"):
        resolve_redirect("https://www.cisa.gov/a", "http://127.0.0.1/secret")
    with pytest.raises(ValueError, match="allowlist"):
        resolve_redirect("https://www.cisa.gov/a", "https://evil.example/catalog.json")
    with pytest.raises(ValueError, match="https"):
        resolve_redirect("https://www.cisa.gov/a", "file:///etc/passwd")


def test_local_paths_are_jailed_to_repo():
    cfg = settings()
    inside = resolve_local(cfg, "local:data/ai_rmf_core.json")
    assert inside.is_file()
    assert inside.resolve().is_relative_to(cfg.root.resolve())
    with pytest.raises(ValueError, match="relative|escapes"):
        resolve_local(cfg, "local:/etc/passwd")
    with pytest.raises(ValueError, match="escapes"):
        resolve_local(cfg, "local:../.env")
    with pytest.raises(ValueError, match="relative|escapes"):
        resolve_local(cfg, f"local:{Path.home() / '.zshrc'}")


def test_cli_help():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
