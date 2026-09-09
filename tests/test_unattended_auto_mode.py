import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from test_pipeline_runtime_contract import package


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


def test_v02_spending_does_not_consume_the_sealed_v01_total_budget(
    auto_batch, monkeypatch
):
    runner, policy, batch, _ = auto_batch("gpt_web")
    assert runner.main(["next", "--batch", str(batch)]) == 0
    state = runner.load_or_create_state(batch, policy)
    item = next(batch.glob("V001_*"))
    state.rerun_budget_by_video["V001"] = "3.00"
    state.budget_ledger["V001:V02"] = {
        "cost": "3.00", "status": "spent"
    }
    monkeypatch.setattr(runner, "_payload_binding", lambda *_: {"offline": True})

    runner._reserve_payment(batch, item, state, "offline-request")

    v01_total = sum(
        (Decimal(row["cost"])
        for attempt, row in state.budget_ledger.items()
        if attempt.endswith("V01")),
        Decimal("0"),
    )
    assert v01_total == Decimal("3.00")
    assert v01_total <= Decimal(state.approved_manifest["reserved_v01_video_yuan"])


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


def _drive_auto_v01(auto_batch, provider, capsys, monkeypatch):
    runner, policy, batch, _ = auto_batch(provider)
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(batch.parent / "unrelated-temp"))
    assert runner.main(["next", "--batch", str(batch)]) == 0
    content_action = json.loads(capsys.readouterr().out)
    content_dir = Path(content_action["output_dir"])
    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / "V001.json").write_text(
        json.dumps(package("V001"), ensure_ascii=False), encoding="utf-8"
    )
    assert runner.main([
        "accept-content", "--batch", str(batch), "--content-dir", str(content_dir),
        "--profile", str(SKILL / "profiles/爱优护电动轮椅_淘宝天猫光合.json"),
        "--action-id", content_action["action_id"],
    ]) == 0
    capsys.readouterr()
    for index in range(3):
        assert runner.main(["next", "--batch", str(batch)]) == 0
        image_action = json.loads(capsys.readouterr().out)
        output = Path(image_action["output_path"])
        Image.new("RGB", (2160, 3840), (index * 40, 60, 120)).save(output)
        assert runner.main([
            "accept-image", "--batch", str(batch), "--video-id", "V001",
            "--artifact", image_action["artifact"], "--source", str(output),
            "--action-id", image_action["action_id"],
        ]) == 0
        capsys.readouterr()
    assert runner.main(["next", "--batch", str(batch)]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "LOCAL_WORK_REQUIRED"
    item = next(batch.glob("V001_*"))

    def execute(batch_dir, item_dir, state, **kwargs):
        info = runner._task_info(item_dir)
        info.update({"task_id": "offline-v01", "request_hash": "offline-request", "submission_pending": False})
        runner._write_task_info(item_dir, info)
        state.budget_ledger["V001:V01"] = {
            "cost": "3.00", "status": "spent", "task_id": "offline-v01",
            "request_hash": "offline-request",
        }
        candidate = item_dir / "_工作文件/生成过程/视频候选.mp4"
        candidate.write_bytes(b"offline-auto-v01")
        technical = {
            "ok": True, "full_decode": True, "has_audio": True,
            "duration": 15.0, "width": 1280, "height": 720,
            "sha256": runner._sha256(candidate), "candidate": str(candidate.resolve()),
        }
        return {"ok": True, "candidate": str(candidate), "technical": technical, "task_id": "offline-v01"}

    monkeypatch.setattr(runner, "run_autodl_item", execute)
    return runner, policy, batch, item


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_auto_delivery_promotes_v01_and_returns_verified_absolute_root_video(
    auto_batch, provider, capsys, monkeypatch
):
    runner, policy, batch, item = _drive_auto_v01(auto_batch, provider, capsys, monkeypatch)

    assert runner.main(["run-local", "--batch", str(batch)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["kind"] == "V01_DELIVERED"
    assert result["status"] == "WAITING_USER_FEEDBACK"
    assert result["kind"] != "USER_FINAL_REVIEW_REQUIRED"
    row = result["items"][0]
    workflow = runner._load_workflow_cli()
    video = Path(row["video_path"])
    item_path = Path(row["item_dir"])
    assert video.is_absolute() and video.is_file()
    assert item_path.is_absolute() and item_path.is_dir()
    assert item_path == item.resolve()
    assert video.parent == item_path
    assert video.name == workflow.deliverable_root_path(item_path, "视频.mp4").name
    assert runner._sha256(video) == row["sha256"] == row["technical"]["sha256"]
    assert row["status"] == "V01 已下载，等待用户反馈"
    assert row["video_cost_yuan"] == "3.00"
    assert row["image_cost_yuan"] == ("0" if provider == "gpt_web" else "0.60")
    assert runner.load_or_create_state(batch, policy).status == "WAITING_USER_FEEDBACK"
    assert (batch / "批次V01交付.json").is_file()


def test_auto_feedback_requires_explicit_v02_budget_without_mutating_ledger(
    auto_batch, capsys, monkeypatch
):
    runner, policy, batch, item = _drive_auto_v01(auto_batch, "third_party_api", capsys, monkeypatch)
    assert runner.main(["run-local", "--batch", str(batch)]) == 0
    capsys.readouterr()
    delivered = runner.load_or_create_state(batch, policy)
    ledger_before = json.dumps(delivered.budget_ledger, sort_keys=True)
    image_ledger_before = json.dumps(delivered.image_budget_ledger, sort_keys=True)
    actions_before = json.dumps(delivered.model_actions, sort_keys=True)

    assert runner.main([
        "approve-rerun", "--batch", str(batch), "--video-id", "V001", "--approved-cost", "3.00"
    ]) == 2
    assert json.loads(capsys.readouterr().out)["kind"] == "COMMAND_REJECTED"
    assert runner.main([
        "request-rerun", "--batch", str(batch), "--video-id", "V001", "--reason", "用户希望调整节奏"
    ]) == 0
    request = json.loads(capsys.readouterr().out)
    assert request["kind"] == "USER_RERUN_APPROVAL_REQUIRED"
    waiting = runner.load_or_create_state(batch, policy)
    assert waiting.status == "WAITING_RERUN_APPROVAL"
    assert json.dumps(waiting.budget_ledger, sort_keys=True) == ledger_before
    assert json.dumps(waiting.image_budget_ledger, sort_keys=True) == image_ledger_before
    assert json.dumps(waiting.model_actions, sort_keys=True) == actions_before
    assert runner._item_retry_count(item) == 0
    assert runner.main([
        "approve-rerun", "--batch", str(batch), "--video-id", "V001", "--approved-cost", "3.00"
    ]) == 0
    capsys.readouterr()
    assert runner._item_retry_count(item) == 1
    assert runner.main([
        "request-rerun", "--batch", str(batch), "--video-id", "V001", "--reason", "禁止 V03"
    ]) == 2
