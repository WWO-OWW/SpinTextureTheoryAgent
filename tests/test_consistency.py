from pathlib import Path

from spintexture_agent.checker import check_task
from spintexture_agent.consistency import check_generated_bundle
from spintexture_agent.generator import generate_task_bundle
from spintexture_agent.ir import build_physics_ir
from spintexture_agent.kb import KnowledgeBase
from spintexture_agent.schema import TheoryTask
from spintexture_agent.selector import select_template


def _bundle(tmp_path):
    task = TheoryTask.from_yaml(Path("configs/afm_stripe_sot.yaml"))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    validation = check_task(task, template, kb, physics_ir)
    return generate_task_bundle(
        task,
        template,
        validation,
        tmp_path,
        physics_ir=physics_ir,
    )


def test_generated_bundle_is_consistent(tmp_path):
    paths = _bundle(tmp_path)
    report = check_generated_bundle(paths["record"], paths["summary"], paths["wolfram"])

    assert report.ok
    assert report.issues == ()


def test_consistency_check_detects_human_report_status_drift(tmp_path):
    paths = _bundle(tmp_path)
    summary = paths["summary"].read_text(encoding="utf-8")
    paths["summary"].write_text(
        summary.replace("`full_derivation`", "`review_only`", 1),
        encoding="utf-8",
    )

    report = check_generated_bundle(paths["record"], paths["summary"], paths["wolfram"])

    assert not report.ok
    assert any(issue.field == "support_level" for issue in report.issues)


def test_consistency_check_detects_evidence_badge_drift(tmp_path):
    paths = _bundle(tmp_path)
    summary = paths["summary"].read_text(encoding="utf-8")
    paths["summary"].write_text(
        summary.replace("`benchmark` | `registered`", "`benchmark` | `passed`", 1),
        encoding="utf-8",
    )

    report = check_generated_bundle(paths["record"], paths["summary"], paths["wolfram"])

    assert not report.ok
    assert any(issue.field == "evidence_status.benchmark" for issue in report.issues)
