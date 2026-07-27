from pathlib import Path

from spintexture_agent.checker import check_task
from spintexture_agent.kb import KnowledgeBase
from spintexture_agent.schema import TheoryTask
from spintexture_agent.selector import select_template


def test_afm_stripe_template_selection():
    task = TheoryTask.from_yaml(Path("configs/afm_stripe_sot.yaml"))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    assert template.name == "afm_stripe_domain_collective_coordinate"
    assert template.dynamics == "sigma_model"
    assert "n" in template.order_parameters


def test_checker_reports_constraints():
    task = TheoryTask.from_yaml(Path("configs/afm_stripe_sot.yaml"))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    report = check_task(task, template, kb)
    assert any("n.n" in item for item in report.checks)


def test_checker_reports_paper_review_items():
    task = TheoryTask.from_yaml(Path("configs/afm_stripe_sot.yaml"))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    report = check_task(task, template, kb)
    item_ids = {item.id for item in report.items}

    assert "collective_boundary_terms" in item_ids
    assert "stripe_stiffness_review" in item_ids
    assert "sot_polarization" in item_ids
