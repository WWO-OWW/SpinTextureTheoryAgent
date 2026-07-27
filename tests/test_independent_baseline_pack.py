import importlib.util
import csv
import json
import sys
import zipfile
from pathlib import Path

import yaml


def _load_pack_module():
    path = Path("analysis/scripts/build_independent_baseline_pack.py")
    spec = importlib.util.spec_from_file_location("build_independent_baseline_pack", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_readiness_module():
    path = Path("analysis/scripts/check_independent_baseline_readiness.py")
    spec = importlib.util.spec_from_file_location("check_independent_baseline_readiness", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_init_module():
    path = Path("analysis/scripts/init_independent_baseline_outputs.py")
    spec = importlib.util.spec_from_file_location("init_independent_baseline_outputs", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_sync_module():
    path = Path("analysis/scripts/sync_independent_baseline_raw_outputs.py")
    spec = importlib.util.spec_from_file_location("sync_independent_baseline_raw_outputs", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_export_module():
    path = Path("analysis/scripts/export_independent_baseline_operator_packet.py")
    spec = importlib.util.spec_from_file_location("export_independent_baseline_operator_packet", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_import_module():
    path = Path("analysis/scripts/import_independent_baseline_operator_packet.py")
    spec = importlib.util.spec_from_file_location("import_independent_baseline_operator_packet", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_worksheet_module():
    path = Path("analysis/scripts/baseline_response_worksheet.py")
    spec = importlib.util.spec_from_file_location("baseline_response_worksheet", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_collection_module():
    path = Path("analysis/scripts/start_independent_baseline_collection.py")
    spec = importlib.util.spec_from_file_location("start_independent_baseline_collection", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_collection_check_module():
    path = Path("analysis/scripts/check_independent_baseline_collection.py")
    spec = importlib.util.spec_from_file_location("check_independent_baseline_collection", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_independent_baseline_pack_writes_protocol(tmp_path):
    module = _load_pack_module()
    paths = module.write_pack(tmp_path / "core3_pack")

    assert paths["manifest"].exists()
    assert paths["readme"].exists()
    assert paths["run_sheet"].exists()
    assert paths["template_llm_only"].exists()
    assert paths["template_naive_llm_wolfram"].exists()

    manifest = yaml.safe_load(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["protocol_id"] == "independent_core3_baseline_v1"
    assert manifest["case_ids"] == [
        "A4_afm_stripe_sot",
        "B1_fm_skyrmion_sot",
        "B2_afm_skyrmion_sot",
    ]

    prompt = paths["prompt_prompted_llm_B2_afm_skyrmion_sot"].read_text(encoding="utf-8")
    assert "Do not inspect benchmark expected fields" in prompt
    assert "gold answers" in prompt
    assert "compensated_two_sublattice_afm" in prompt
    assert "expected:" not in prompt

    template = yaml.safe_load(paths["template_llm_only"].read_text(encoding="utf-8"))
    assert template["method_id"] == "llm_only"
    assert set(template["cases"]) == set(manifest["case_ids"])
    assert template["cases"]["A4_afm_stripe_sot"]["raw_output_provenance"] == {
        "source_file": None,
        "sha256": None,
        "synced_at": None,
    }
    response = template["cases"]["A4_afm_stripe_sot"]["response"]
    assert response["wolfram_execution"]["status"] is None
    assert response["wolfram_results"]["results"] is None


def test_init_independent_baseline_outputs_is_non_destructive(tmp_path):
    pack_module = _load_pack_module()
    init_module = _load_init_module()
    out_dir = tmp_path / "core3_pack"
    pack_module.write_pack(out_dir)

    first = init_module.init_completed_outputs(protocol_dir=out_dir)
    assert Path(first["checklist"]).exists()
    assert {item["status"] for item in first["outputs"]} == {"created"}

    completed = out_dir / "completed_outputs" / "llm_only.yaml"
    original = completed.read_text(encoding="utf-8")
    completed.write_text(original + "\n# local edit should survive default init\n", encoding="utf-8")

    second = init_module.init_completed_outputs(protocol_dir=out_dir)
    assert {item["status"] for item in second["outputs"]} == {"skipped_existing"}
    assert "local edit should survive" in completed.read_text(encoding="utf-8")

    forced = init_module.init_completed_outputs(protocol_dir=out_dir, force=True)
    assert {item["status"] for item in forced["outputs"]} == {"overwritten"}
    assert "local edit should survive" not in completed.read_text(encoding="utf-8")


def test_sync_independent_raw_outputs_preserves_response_fields(tmp_path):
    pack_module = _load_pack_module()
    init_module = _load_init_module()
    sync_module = _load_sync_module()
    out_dir = tmp_path / "core3_pack"
    pack_module.write_pack(out_dir)
    init_module.init_completed_outputs(protocol_dir=out_dir)

    init_raw = sync_module.init_raw_output_files(out_dir)
    assert {item["status"] for item in init_raw["files"]} == {"created"}

    raw_path = out_dir / "raw_outputs" / "llm_only" / "A4_afm_stripe_sot.md"
    raw_path.write_text(
        "\n".join(
            [
                "# Raw Output: llm_only / A4_afm_stripe_sot",
                "",
                "--- PASTE RAW OUTPUT BELOW THIS LINE ---",
                "",
                "This is the exact raw external answer for A4. It is intentionally long enough.",
            ]
        ),
        encoding="utf-8",
    )

    completed_path = out_dir / "completed_outputs" / "llm_only.yaml"
    payload = yaml.safe_load(completed_path.read_text(encoding="utf-8"))
    payload["cases"]["A4_afm_stripe_sot"]["response"]["material_class"] = "keep_me"
    completed_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = sync_module.sync_raw_outputs_to_completed(protocol_dir=out_dir)
    assert len(result["synced"]) == 1
    assert result["synced"][0]["case_id"] == "A4_afm_stripe_sot"
    assert result["skipped"]

    updated = yaml.safe_load(completed_path.read_text(encoding="utf-8"))
    case = updated["cases"]["A4_afm_stripe_sot"]
    assert "exact raw external answer" in case["raw_output"]
    assert case["raw_output_provenance"]["source_file"] == str(raw_path)
    assert len(case["raw_output_provenance"]["sha256"]) == 64
    assert case["raw_output_provenance"]["synced_at"].endswith("Z")
    assert case["response"]["material_class"] == "keep_me"

    second = sync_module.init_raw_output_files(out_dir)
    assert {item["status"] for item in second["files"]} == {"skipped_existing"}
    assert "exact raw external answer" in raw_path.read_text(encoding="utf-8")


def test_independent_baseline_readiness_checker(tmp_path):
    pack_module = _load_pack_module()
    readiness_module = _load_readiness_module()
    init_module = _load_init_module()
    sync_module = _load_sync_module()
    out_dir = tmp_path / "core3_pack"
    pack_module.write_pack(out_dir)

    incomplete = readiness_module.check_readiness(
        protocol_dir=out_dir,
        outputs_dir=out_dir / "completed_outputs",
    )
    assert not incomplete["ready"]
    assert "missing completed output file" in incomplete["methods"][0]["issues"][0]

    init_module.init_completed_outputs(protocol_dir=out_dir)
    sync_module.init_raw_output_files(protocol_dir=out_dir)
    for raw_path in sorted((out_dir / "raw_outputs").glob("*/*.md")):
        raw_path.write_text(
            "\n".join(
                [
                    raw_path.read_text(encoding="utf-8"),
                    "Synthetic independent raw output collected from an external method. "
                    "This transcript is intentionally long enough for the readiness checker.",
                ]
            ),
            encoding="utf-8",
        )
    sync_module.sync_raw_outputs_to_completed(protocol_dir=out_dir)

    completed_dir = out_dir / "completed_outputs"
    for completed_path in sorted(completed_dir.glob("*.yaml")):
        payload = yaml.safe_load(completed_path.read_text(encoding="utf-8"))
        payload["provenance"]["runner"] = "unit_test_runner"
        payload["provenance"]["model_or_method"] = payload["method_id"]
        payload["provenance"]["run_date"] = "2026-07-08"
        payload["provenance"]["notes"] = "synthetic structurally complete readiness fixture"
        for case_id, case in payload["cases"].items():
            response = case["response"]
            response["material_class"] = "filled_material"
            response["primary_order_parameter"] = "filled_order_parameter"
            response["dynamics_type"] = "filled_dynamics"
            response["equation_type"] = "filled_equation"
            response["topology_field"] = "filled_topology"
            response["wolfram_execution"]["status"] = "not_executed"
        completed_path.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

    complete = readiness_module.check_readiness(protocol_dir=out_dir, outputs_dir=completed_dir)
    assert complete["ready"]
    assert "Ready for scoring: `True`" in readiness_module.render_report(complete)


def test_export_independent_baseline_operator_packet_is_blinded(tmp_path):
    pack_module = _load_pack_module()
    export_module = _load_export_module()
    protocol_dir = tmp_path / "core3_pack"
    packet_dir = tmp_path / "operator_packet"
    zip_path = tmp_path / "operator_packet.zip"
    pack_module.write_pack(protocol_dir)

    result = export_module.export_operator_packet(
        protocol_dir=protocol_dir,
        out_dir=packet_dir,
        zip_path=zip_path,
    )

    assert result["prompt_count"] == 12
    assert result["raw_template_count"] == 12
    assert packet_dir.exists()
    assert zip_path.exists()

    raw_template = packet_dir / "raw_outputs" / "llm_only" / "A4_afm_stripe_sot.md"
    raw_text = raw_template.read_text(encoding="utf-8")
    assert "PASTE RAW OUTPUT BELOW THIS LINE" in raw_text
    assert "prompts/llm_only/A4_afm_stripe_sot.md" in raw_text
    assert str(protocol_dir) not in raw_text

    packet_manifest = json.loads((packet_dir / "packet_manifest.json").read_text(encoding="utf-8"))
    included_paths = {record["path"] for record in packet_manifest["included_files"]}
    forbidden_prefixes = (
        "completed_outputs/",
        "response_templates/",
        "gold_answers/",
        "benchmark_cases/",
        "benchmark_case_sets/",
        "outputs/",
    )
    assert not any(path.startswith(forbidden_prefixes) for path in included_paths)

    prompt_text = (packet_dir / "prompts" / "prompted_llm" / "B2_afm_skyrmion_sot.md").read_text(
        encoding="utf-8"
    )
    assert "expected:" not in prompt_text
    assert "compensated_two_sublattice_afm" in prompt_text

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert "operator_log.md" in names
    assert "raw_outputs/llm_only/A4_afm_stripe_sot.md" in names
    assert not any(name.startswith(forbidden_prefixes) for name in names)


def test_import_independent_baseline_operator_packet_from_zip(tmp_path):
    pack_module = _load_pack_module()
    init_module = _load_init_module()
    sync_module = _load_sync_module()
    export_module = _load_export_module()
    import_module = _load_import_module()

    protocol_dir = tmp_path / "core3_pack"
    packet_dir = tmp_path / "operator_packet"
    returned_zip = tmp_path / "returned_operator_packet.zip"
    pack_module.write_pack(protocol_dir)
    init_module.init_completed_outputs(protocol_dir=protocol_dir)
    sync_module.init_raw_output_files(protocol_dir=protocol_dir)
    export_module.export_operator_packet(
        protocol_dir=protocol_dir,
        out_dir=packet_dir,
        zip_path=tmp_path / "blank_operator_packet.zip",
    )

    for raw_path in sorted((packet_dir / "raw_outputs").glob("*/*.md")):
        method_id = raw_path.parent.name
        case_id = raw_path.stem
        raw_path.write_text(
            "\n".join(
                [
                    raw_path.read_text(encoding="utf-8"),
                    f"External baseline transcript for {method_id} on {case_id}. "
                    "This is long enough to be accepted by the import checker.",
                ]
            ),
            encoding="utf-8",
        )
    (packet_dir / "operator_log.md").write_text(
        "\n".join(
            [
                "# Operator Log",
                "",
                "- Operator: unit-test operator",
                "- Collection date: 2026-07-09",
                "- Environment: local fixture",
            ]
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(returned_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(packet_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(packet_dir))

    result = import_module.import_operator_packet(
        returned_zip,
        protocol_dir=protocol_dir,
        label="unit_test_return",
    )

    assert result["ready_for_sync"]
    assert not result["issues"]
    assert result["copied_raw_outputs"] == 12
    assert Path(result["operator_log"]).exists()
    assert Path(result["report_path"]).exists()

    imported_raw = protocol_dir / "raw_outputs" / "llm_only" / "A4_afm_stripe_sot.md"
    assert "External baseline transcript" in imported_raw.read_text(encoding="utf-8")

    sync_result = sync_module.sync_raw_outputs_to_completed(protocol_dir=protocol_dir)
    assert len(sync_result["synced"]) == 12
    completed = yaml.safe_load((protocol_dir / "completed_outputs" / "llm_only.yaml").read_text())
    provenance = completed["cases"]["A4_afm_stripe_sot"]["raw_output_provenance"]
    assert provenance["source_file"].endswith("raw_outputs/llm_only/A4_afm_stripe_sot.md")
    assert len(provenance["sha256"]) == 64


def test_import_independent_baseline_operator_packet_rejects_blank_packet(tmp_path):
    pack_module = _load_pack_module()
    export_module = _load_export_module()
    import_module = _load_import_module()

    protocol_dir = tmp_path / "core3_pack"
    packet_dir = tmp_path / "operator_packet"
    pack_module.write_pack(protocol_dir)
    export_module.export_operator_packet(
        protocol_dir=protocol_dir,
        out_dir=packet_dir,
        zip_path=None,
    )

    result = import_module.import_operator_packet(
        packet_dir,
        protocol_dir=protocol_dir,
        label="blank_packet",
        dry_run=True,
    )

    assert not result["ready_for_sync"]
    assert result["copied_raw_outputs"] == 0
    assert any("raw output is empty" in issue for issue in result["issues"])


def test_baseline_response_worksheet_round_trip(tmp_path):
    pack_module = _load_pack_module()
    init_module = _load_init_module()
    sync_module = _load_sync_module()
    readiness_module = _load_readiness_module()
    worksheet_module = _load_worksheet_module()
    protocol_dir = tmp_path / "core3_pack"
    pack_module.write_pack(protocol_dir)
    init_module.init_completed_outputs(protocol_dir=protocol_dir)
    sync_module.init_raw_output_files(protocol_dir=protocol_dir)

    for raw_path in sorted((protocol_dir / "raw_outputs").glob("*/*.md")):
        raw_path.write_text(
            "\n".join(
                [
                    raw_path.read_text(encoding="utf-8"),
                    "External raw baseline answer. It contains enough text for readiness checks.",
                ]
            ),
            encoding="utf-8",
        )
    sync_module.sync_raw_outputs_to_completed(protocol_dir=protocol_dir)

    worksheet_path = protocol_dir / "response_extraction_worksheet.csv"
    export_result = worksheet_module.export_worksheet(
        protocol_dir=protocol_dir,
        worksheet_path=worksheet_path,
    )
    assert export_result["row_count"] == 12

    with worksheet_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None

    for row in rows:
        row["runner"] = "unit_test_runner"
        row["model_or_method"] = row["method_id"]
        row["run_date"] = "2026-07-09"
        row["provenance_notes"] = "worksheet round-trip fixture"
        case_id = row["case_id"]
        if case_id == "B1_fm_skyrmion_sot":
            row["material_class"] = "ferromagnet"
            row["primary_order_parameter"] = "m"
            row["dynamics_type"] = "llg"
            row["equation_type"] = "thiele_equation"
            row["topology_field"] = "m"
        elif case_id == "B2_afm_skyrmion_sot":
            row["material_class"] = "collinear_antiferromagnet"
            row["primary_order_parameter"] = "n"
            row["dynamics_type"] = "sigma_model"
            row["equation_type"] = "inertial_collective_coordinate"
            row["topology_field"] = "n"
        else:
            row["material_class"] = "collinear_antiferromagnet"
            row["primary_order_parameter"] = "n"
            row["dynamics_type"] = "sigma_model"
            row["equation_type"] = "coupled_wall_chain"
            row["topology_field"] = "n"
        row["assumptions"] = '["manual extraction fixture"]'
        row["limit_checks"] = '["alpha -> 0 gives conservative dynamics"]'
        row["energy_terms"] = '["exchange"]'
        row["wolfram_symbols"] = "[]"
        row["validation_ids"] = "[]"
        row["requires_human_review"] = "false"
        row["wolfram_execution_status"] = "not_executed"
        row["wolfram_results_json"] = ""
        row["reviewer"] = "unit-test reviewer"
        row["review_notes"] = "structured extraction completed"

    with worksheet_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    import_result = worksheet_module.import_worksheet(
        protocol_dir=protocol_dir,
        worksheet_path=worksheet_path,
    )
    assert import_result["updated_cases"] == 12
    assert Path(import_result["report_path"]).exists()

    completed = yaml.safe_load((protocol_dir / "completed_outputs" / "llm_only.yaml").read_text())
    case = completed["cases"]["B1_fm_skyrmion_sot"]
    assert case["response"]["material_class"] == "ferromagnet"
    assert case["response"]["primary_order_parameter"] == "m"
    assert case["response"]["wolfram_execution"]["status"] == "not_executed"
    assert case["response_extraction"]["reviewer"] == "unit-test reviewer"
    assert case["raw_output_provenance"]["sha256"]

    readiness = readiness_module.check_readiness(protocol_dir=protocol_dir)
    assert readiness["ready"]


def test_start_independent_baseline_collection_run(tmp_path):
    pack_module = _load_pack_module()
    export_module = _load_export_module()
    collection_module = _load_collection_module()
    protocol_dir = tmp_path / "core3_pack"
    packet_zip = protocol_dir / "blinded_operator_packet.zip"
    pack_module.write_pack(protocol_dir)
    export_module.export_operator_packet(
        protocol_dir=protocol_dir,
        out_dir=protocol_dir / "blinded_operator_packet",
        zip_path=packet_zip,
    )

    result = collection_module.start_collection_run(
        run_id="external_run_unit_test",
        protocol_dir=protocol_dir,
        runs_dir=protocol_dir / "collection_runs",
        packet_zip=packet_zip,
    )

    run_dir = Path(result["run_dir"])
    assert run_dir.exists()
    assert Path(result["packet_zip"]).exists()
    assert len(result["packet_sha256"]) == 64
    assert result["expected_raw_outputs"] == 12

    status_rows = list(csv.DictReader(Path(result["collection_status"]).open(encoding="utf-8")))
    assert len(status_rows) == 12
    assert {row["status"] for row in status_rows} == {"pending"}

    request = Path(result["operator_request"]).read_text(encoding="utf-8")
    assert "Do not inspect `gold_answers/`" in request
    assert "raw_outputs/<method_id>/<case_id>.md" in request


def test_check_independent_baseline_collection_run(tmp_path):
    pack_module = _load_pack_module()
    export_module = _load_export_module()
    collection_module = _load_collection_module()
    check_module = _load_collection_check_module()
    protocol_dir = tmp_path / "core3_pack"
    packet_zip = protocol_dir / "blinded_operator_packet.zip"
    pack_module.write_pack(protocol_dir)
    export_module.export_operator_packet(
        protocol_dir=protocol_dir,
        out_dir=protocol_dir / "blinded_operator_packet",
        zip_path=packet_zip,
    )
    start = collection_module.start_collection_run(
        run_id="external_run_unit_test",
        protocol_dir=protocol_dir,
        runs_dir=protocol_dir / "collection_runs",
        packet_zip=packet_zip,
    )

    report = check_module.check_collection_run(start["run_dir"])

    assert report["ready_for_operator_dispatch"]
    assert not report["ready_for_import"]
    assert report["next_action"] == "send_blinded_packet_to_operator"
    assert report["status_counts"]["pending"] == 12
    assert Path(report["report_json"]).exists()
    assert Path(report["report_md"]).exists()

    returned = Path(start["run_dir"]) / "returned_operator_packet.zip"
    returned.write_bytes(Path(start["packet_zip"]).read_bytes())
    returned_report = check_module.check_collection_run(start["run_dir"])

    assert returned_report["ready_for_import"]
    assert returned_report["next_action"] == "import_returned_operator_packet"
    assert returned_report["returned_candidates"] == [str(returned)]

    status_path = Path(start["run_dir"]) / "collection_status.csv"
    rows = list(csv.DictReader(status_path.open(encoding="utf-8")))
    with status_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            row["status"] = "scored"
            writer.writerow(row)

    scored_report = check_module.check_collection_run(start["run_dir"])
    assert not scored_report["ready_for_import"]
    assert scored_report["next_action"] == "collection_complete"
    assert scored_report["status_counts"]["scored"] == 12
