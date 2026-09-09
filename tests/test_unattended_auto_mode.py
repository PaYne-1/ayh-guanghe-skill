import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill-package" / "product-video-pipeline" / "scripts"
SKILL = ROOT / "skill-package" / "product-video-pipeline"


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"auto_{name}", SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def auto_batch(tmp_path, monkeypatch):
    workflow = load_script("workflow_cli.py")
    runner = load_script("pipeline_runner.py")
    policy = load_script("pipeline_policy.py").load_policy(SKILL)
    product = tmp_path / "product"
    covers = tmp_path / "covers"
    product.mkdir()
    covers.mkdir()
    (product / "reference.png").write_bytes(b"product reference")
    (covers / "cover.png").write_bytes(b"cover reference")

    def create(provider, total_budget="5.00"):
        config = None
        if provider == "third_party_api":
            monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "offline-only")
            config = {
                "api_name": "Example Images",
                "base_url": "https://images.example.test/v1",
                "model": "image-v1",
                "api_key_env": "EXAMPLE_IMAGE_API_KEY",
                "unit_price_yuan": "0.20",
            }
        context = workflow.initialize_batch(
            product_dir=product,
            product_name="测试产品",
            selling_points=["轻便"],
            total_videos=1,
            run_mode="auto",
            resolution="768P",
            max_budget_yuan=total_budget,
            cover_reference_dir=covers,
            knowledge_dir=tmp_path / "knowledge",
            image_provider=provider,
            image_api_config=config,
            now=datetime(2026, 9, 9, tzinfo=timezone.utc),
        )
        confirmation_path = context.batch_dir / "启动确认单.json"
        confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
        confirmation["prices_by_video"] = {"V001": "3.00"}
        confirmation_path.write_text(
            json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
        )
        return runner, policy, context.batch_dir, confirmation

    return create


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_auto_initial_reply_activates_v01_without_approve_start(auto_batch, provider, capsys):
    runner, policy, batch, confirmation = auto_batch(provider)

    assert confirmation["startup_authorization"] == "initial_user_reply"
    assert confirmation["max_budget_yuan"] == "5.00"
    assert runner.main(["next", "--batch", str(batch)]) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["kind"] == "BATCH_CONTENT_REQUIRED"

    state = runner.load_or_create_state(batch, policy)
    assert state.status == "RUNNING_AUTOMATICALLY"
    assert state.approved_manifest["run_mode"] == "auto"
    assert state.approved_manifest["reserved_v01_video_yuan"] == "3.00"


def test_auto_total_budget_reserves_video_before_third_party_images(auto_batch):
    runner, policy, batch, _ = auto_batch("third_party_api")

    assert runner.main(["next", "--batch", str(batch)]) == 0
    state = runner.load_or_create_state(batch, policy)
    manifest = state.approved_manifest
    assert manifest["total_budget_yuan"] == "5.00"
    assert manifest["reserved_v01_video_yuan"] == "3.00"
    assert manifest["initial_image_estimate_yuan"] == "0.60"
    assert manifest["image_budget_yuan"] == "2.00"
    assert state.approved_budget == "5.00"
    assert state.estimated_v01_total == "3.00"
    assert state.image_budget_ledger == {}


def test_auto_blocks_before_actions_when_total_cannot_cover_v01_and_initial_images(auto_batch):
    runner, policy, batch, _ = auto_batch("third_party_api", total_budget="3.50")

    assert runner.main(["next", "--batch", str(batch)]) == 0
    state = runner.load_or_create_state(batch, policy)
    assert state.status == "BLOCKED"
    assert state.model_actions == {}
    assert state.image_budget_ledger == {}
    assert state.budget_ledger == {}


def test_gpt_web_auto_manifest_has_no_image_charge_or_ledger(auto_batch):
    runner, policy, batch, _ = auto_batch("gpt_web")

    assert runner.main(["next", "--batch", str(batch)]) == 0
    state = runner.load_or_create_state(batch, policy)
    assert state.approved_manifest["initial_image_estimate_yuan"] == "0"
    assert state.image_budget_ledger == {}


def test_v01_video_reservation_cannot_exceed_its_sealed_budget(auto_batch, monkeypatch):
    runner, policy, batch, _ = auto_batch("gpt_web")
    assert runner.main(["next", "--batch", str(batch)]) == 0
    state = runner.load_or_create_state(batch, policy)
    item = next(batch.glob("V001_*"))
    state.budget_ledger["earlier:V01"] = {
        "cost": "3.00", "status": "spent"
    }
    monkeypatch.setattr(runner, "_payload_binding", lambda *_: {"offline": True})

    with pytest.raises(PermissionError, match="V01 视频费用超过已预留视频预算"):
        runner._reserve_payment(batch, item, state, "offline-request")
    assert "V001:V01" not in state.budget_ledger


def test_legacy_confirmation_without_run_mode_keeps_learning_start_gate(auto_batch):
    runner, policy, batch, _ = auto_batch("gpt_web")
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation.pop("run_mode")
    confirmation.pop("startup_authorization")
    confirmation_path.write_text(
        json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
    )

    state = runner.load_or_create_state(batch, policy)
    assert runner.next_action(batch, state, policy) == {
        "kind": "USER_START_APPROVAL_REQUIRED"
    }
