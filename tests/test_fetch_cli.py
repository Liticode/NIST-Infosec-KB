import pytest

from atlas.cli import main
from atlas.fetch import assert_allowed_url


def test_allowlist_rejects_unknown_host():
    with pytest.raises(ValueError, match="allowlist"):
        assert_allowed_url("https://evil.example/catalog.json")


def test_allowlist_accepts_nist_github_and_cisa():
    assert_allowed_url(
        "https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog-min.json"
    )
    assert_allowed_url("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")


def test_cli_help():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
