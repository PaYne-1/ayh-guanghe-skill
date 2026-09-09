import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill-package" / "product-video-pipeline" / "scripts"


def load_contract():
    spec = importlib.util.spec_from_file_location(
        "generation_prompt_contract", SCRIPTS / "generation_prompt_contract.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def contract():
    return load_contract()


def test_image_prompt_uses_reference_as_only_product_source(contract):
    prompt = contract.compile_image_prompt("老人和家属在公园出行", "分镜图.png")

    assert "产品参考图是唯一产品依据" in prompt
    assert "禁止重新设计、补画、删减、替换或推测" in prompt
    assert "2160×3840" in prompt
    assert "8,294,400" in prompt
    assert prompt.count(contract.PRODUCT_REFERENCE_BLOCK) == 1
    assert prompt.count(contract.NATIVE_4K_BLOCK) == 1
    assert contract.validate_image_request(
        prompt, ["产品参考图.png"], 2160, 3840
    ) == []


@pytest.mark.parametrize(
    "appearance",
    ["黑色脚踏板", "红色车架", "加粗轮胎", "圆形控制器"],
)
def test_specific_product_appearance_is_rejected(contract, appearance):
    with pytest.raises(ValueError, match="产品外观"):
        contract.compile_image_prompt(
            f"老人坐在带有{appearance}的产品上", "分镜图.png"
        )


@pytest.mark.parametrize(
    "scene",
    [
        "老人手放控制器上，自然向家属说明操作。",
        "始终保持扶手结构一致，不要改变靠背。",
        "老人穿红色衣服，手放控制器。",
        "按控制器增加速度，老人自然前进。",
    ],
)
def test_component_action_or_reference_lock_is_not_product_appearance_description(
    contract, scene
):
    assert contract.compile_image_prompt(scene, "分镜图.png").startswith(scene)


def test_image_contract_allows_safe_area_composition_without_product_inference(contract):
    prompt = contract.compile_image_prompt(
        "产品整体始终完整位于画面安全区，老人和家属自然同行", "尾帧图.png"
    )

    assert "产品整体始终完整位于画面安全区" in prompt


@pytest.mark.parametrize("artifact", ["分镜图.png", "尾帧图.png", "封面图.png"])
def test_image_contract_accepts_the_three_supported_artifacts(contract, artifact):
    assert contract.compile_image_prompt("公园出行", artifact).startswith("公园出行")


def test_image_contract_rejects_unknown_artifact(contract):
    with pytest.raises(ValueError, match="artifact"):
        contract.compile_image_prompt("公园出行", "产品图.png")


def test_image_validator_returns_stable_codes_without_editing_prompt(contract):
    prompt = "普通图片提示词"

    assert contract.validate_image_request(prompt, [], 1920, 1080) == [
        "image.reference_missing",
        "image.reference_lock_missing",
        "image.native_4k_missing",
        "image.dimensions_invalid",
    ]
    assert prompt == "普通图片提示词"


def test_image_validator_rejects_forbidden_product_appearance(contract):
    prompt = contract.compile_image_prompt("公园出行", "分镜图.png") + "\n红色车架。"

    assert contract.validate_image_request(
        prompt, ["产品参考图.png"], 2160, 3840
    ) == ["image.product_appearance_forbidden"]


@pytest.fixture
def people():
    return [
        {"id": "P1", "identity": "老人"},
        {"id": "P2", "identity": "家属"},
    ]


@pytest.fixture
def segments():
    return [
        {"start": 0, "end": 5, "speaker_id": "P1", "dialogue": "今天出门会不会累？"},
        {"start": 5, "end": 10, "speaker_id": "P2", "dialogue": "坐得稳，路上很轻松。"},
        {"start": 10, "end": 15, "speaker_id": "P1", "dialogue": "确实方便，现在就下单。"},
    ]


def test_video_prompt_locks_single_shot_and_dialogue_contract(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)

    for rule in (
        "产品参考图是唯一产品依据",
        "0–15秒",
        "一个连续镜头",
        "固定中远景",
        "人物全身和产品整体始终完整位于画面安全区",
        "严格交替说话",
        "非当前说话者嘴巴闭合且完全不发声",
        "清单之外零人声",
        "最后一句台词结束后，所有人物闭嘴，不再开口",
        "不得添加任何额外语音",
        "只使用原生中文台词",
        "不得添加背景音乐",
    ):
        assert rule in prompt
    for segment in segments:
        assert prompt.count(segment["dialogue"]) == 1
    assert "P1（老人）" in prompt
    assert "P2（家属）" in prompt
    assert contract.validate_video_request(prompt, segments) == []


@pytest.mark.parametrize(
    "start,end",
    [(-1, 5), (0, 16), (15, 16), (5, 5)],
)
def test_video_contract_rejects_segments_outside_the_15_second_window(
    contract, people, segments, start, end
):
    invalid = [dict(segment) for segment in segments]
    invalid[0]["start"] = start
    invalid[0]["end"] = end

    with pytest.raises(ValueError, match="0–15"):
        contract.compile_video_prompt("公园内自然同行", people, invalid)


def test_video_contract_rejects_duplicate_dialogue_during_compilation(
    contract, people, segments
):
    invalid = [dict(segment) for segment in segments]
    invalid[1]["dialogue"] = invalid[0]["dialogue"]

    with pytest.raises(ValueError, match="台词"):
        contract.compile_video_prompt("公园内自然同行", people, invalid)


def test_video_recompile_does_not_duplicate_product_reference_lock(
    contract, people, segments
):
    base = "公园内自然同行\n" + contract.PRODUCT_REFERENCE_BLOCK

    prompt = contract.compile_video_prompt(base, people, segments)

    assert prompt.count(contract.PRODUCT_REFERENCE_BLOCK) == 1


def test_video_validator_rejects_missing_closed_dialogue_rule(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)
    mutated = prompt.replace("最后一句台词结束后，所有人物闭嘴，不再开口。", "")

    assert "video.closed_dialogue_missing" in contract.validate_video_request(
        mutated, segments
    )


def test_video_validator_rejects_missing_non_speaker_silence_rule(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)
    mutated = prompt.replace("非当前说话者嘴巴闭合且完全不发声。", "")

    assert "video.non_speaker_silence_missing" in contract.validate_video_request(
        mutated, segments
    )


def test_video_validator_rejects_missing_speaker_identity_mapping(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)
    mutated = prompt.replace("P1（老人）", "P1")

    assert "video.speaker_identity_missing" in contract.validate_video_request(
        mutated, segments
    )


def test_video_validator_rejects_duplicated_dialogue(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)
    duplicated = f"{prompt}\n{segments[0]['dialogue']}"

    assert "video.dialogue_exactly_once" in contract.validate_video_request(
        duplicated, segments
    )


def test_video_validator_rejects_extra_voice_permission(contract, people, segments):
    prompt = contract.compile_video_prompt("公园内自然同行", people, segments)
    mutated = prompt + "\n允许额外人声作为环境口播。"

    assert "video.extra_voice_permission_forbidden" in contract.validate_video_request(
        mutated, segments
    )


def test_video_contract_rejects_inferred_appearance(contract, people, segments):
    with pytest.raises(ValueError, match="产品外观"):
        contract.compile_video_prompt("红色车架在阳光下行驶", people, segments)


@pytest.mark.parametrize(
    "scene",
    [
        "老人手放控制器上，自然向家属说明操作。",
        "始终保持扶手结构一致，不要改变靠背。",
    ],
)
def test_video_contract_allows_component_action_and_reference_lock(
    contract, people, segments, scene
):
    assert contract.compile_video_prompt(scene, people, segments).startswith(scene)


@pytest.mark.parametrize(
    "appearance",
    ["塑料扶手", "增大踏板"],
)
def test_component_bound_appearance_or_redesign_is_rejected(contract, appearance):
    with pytest.raises(ValueError, match="产品外观"):
        contract.compile_image_prompt(f"自然出行，{appearance}清晰可见。", "分镜图.png")


def test_video_contract_requires_two_distinct_people_and_ordered_non_overlapping_segments(
    contract, people, segments
):
    with pytest.raises(ValueError, match="两名不同人物"):
        contract.compile_video_prompt("公园", [people[0], people[0]], segments)
    overlapping = [dict(segment) for segment in segments]
    overlapping[1]["start"] = 4
    with pytest.raises(ValueError, match="时间段"):
        contract.compile_video_prompt("公园", people, overlapping)
