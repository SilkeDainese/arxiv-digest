from pathlib import Path

import yaml


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "digest.yml"


def _load_workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def _step_by_name(workflow, name):
    steps = workflow["jobs"]["send-digest"]["steps"]
    return next(step for step in steps if step["name"] == name)


def test_digest_workflow_passes_relay_token_to_check_and_run_steps():
    workflow = _load_workflow()

    check_step = _step_by_name(workflow, "Check config")
    run_step = _step_by_name(workflow, "Run digest")

    assert check_step["env"]["DIGEST_RELAY_TOKEN"] == "${{ secrets.DIGEST_RELAY_TOKEN }}"
    assert run_step["env"]["DIGEST_RELAY_TOKEN"] == "${{ secrets.DIGEST_RELAY_TOKEN }}"


def test_digest_workflow_requires_a_real_email_delivery_method():
    workflow = _load_workflow()
    check_step = _step_by_name(workflow, "Check config")
    script = check_step["run"]

    assert 'elif [ -n "$DIGEST_RELAY_TOKEN" ]; then' in script
    assert "Relay token found — sending through shared relay" in script
    assert "No email delivery method configured." in script
    assert "No AI key configured — using keyword fallback" in script
