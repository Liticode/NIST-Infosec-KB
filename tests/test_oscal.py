import json
from pathlib import Path

from atlas.oscal import apply_baselines, parse_baseline_ids, parse_oscal_catalog

FIXTURES = Path(__file__).parent / "fixtures"


def test_catalog_emits_statement_and_assessment():
    payload = json.loads((FIXTURES / "tiny_catalog.json").read_text())
    source = {
        "namespace": "sp800-53-r5",
        "framework": "sp800-53",
        "version": "5.2.0",
        "source_url": "https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final",
        "also_emit_assessment_namespace": "sp800-53a",
        "kind": "statement",
    }
    records = parse_oscal_catalog(payload, source)
    kinds = {r.kind for r in records}
    assert kinds == {"statement", "assessment"}
    statement = next(r for r in records if r.kind == "statement")
    assert "AC-2" in statement.control_id
    assert "approval conditions" in statement.text
    assert "ac-3" in statement.related_ids
    assessment = next(r for r in records if r.kind == "assessment")
    assert "account types are defined" in assessment.text
    assert assessment.namespace == "sp800-53a"


def test_baseline_membership_flags():
    catalog = json.loads((FIXTURES / "tiny_catalog.json").read_text())
    profile = json.loads((FIXTURES / "tiny_profile.json").read_text())
    records = parse_oscal_catalog(
        catalog,
        {
            "namespace": "sp800-53-r5",
            "framework": "sp800-53",
            "version": "5.2.0",
            "source_url": "https://example.invalid",
            "kind": "statement",
        },
    )
    apply_baselines(records, {"moderate": parse_baseline_ids(profile)})
    assert records[0].in_moderate is True
    assert records[0].in_low is False
