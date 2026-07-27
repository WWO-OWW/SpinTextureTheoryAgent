import copy
from pathlib import Path

import pytest
import yaml

from spintexture_agent.literature import LiteratureReproductionRecord


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENDED_RECORDS = PROJECT_ROOT / "literature_reproduction_records/extended"


def _payload(name: str) -> dict[str, object]:
    return yaml.safe_load((EXTENDED_RECORDS / name).read_text(encoding="utf-8"))


def test_extended_literature_records_are_located_hashed_and_bounded():
    records = [
        LiteratureReproductionRecord.from_yaml(path)
        for path in sorted(EXTENDED_RECORDS.glob("*.yaml"))
    ]

    assert {record.case_id for record in records} == {
        "B4_fm_antiskyrmion_sot",
        "C2_fm_meron_topology",
        "C3_fm_bimeron_topology",
        "C4_fm_vortex_topology",
    }
    for record in records:
        assert all(locator.printed_page for locator in record.locators)
        assert all(
            locator.equation_label or locator.section for locator in record.locators
        )
        for claim in record.claims:
            if claim.coverage == "exact":
                assert claim.executable_transform is not None
                assert claim.reproduction_class in {
                    "exact_coefficient",
                    "exact_normalized",
                    "boundary_conditioned_exact",
                }
            else:
                assert claim.reproduction_class == "structural_alignment"


def test_exact_claim_rejects_missing_executable_expression_assertion(tmp_path):
    payload = _payload("C2_fm_meron_topology.yaml")
    claim = payload["claims"][0]
    claim["assertions"] = [
        assertion
        for assertion in claim["assertions"]
        if assertion["path"] != "literature_meron_source_charge"
    ]
    path = tmp_path / "missing_source_assertion.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="must assert Wolfram key"):
        LiteratureReproductionRecord.from_yaml(path)


def test_locator_rejects_doi_only_page(tmp_path):
    payload = copy.deepcopy(_payload("C4_fm_vortex_topology.yaml"))
    payload["locators"][0]["printed_page"] = "DOI-only"
    path = tmp_path / "doi_only.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="printed page"):
        LiteratureReproductionRecord.from_yaml(path)


def test_reproduction_class_cannot_overstate_structural_claim(tmp_path):
    payload = _payload("B4_fm_antiskyrmion_sot.yaml")
    payload["claims"][1]["reproduction_class"] = "exact_coefficient"
    path = tmp_path / "overstated_structural.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="reproduction_class"):
        LiteratureReproductionRecord.from_yaml(path)
