"""Locked prompt contracts for native-4K images and 15-second videos."""

from __future__ import annotations

from typing import Mapping, Sequence


IMAGE_SIZE = (2160, 3840)
IMAGE_ARTIFACTS = {"分镜图.png", "尾帧图.png", "封面图.png"}
FORBIDDEN_PRODUCT_APPEARANCE_TERMS = (
    "踏板",
    "脚踏",
    "车架",
    "轮胎",
    "控制器",
    "扶手",
    "靠背",
)

PRODUCT_REFERENCE_BLOCK = """【产品参考锁定】
上传的产品参考图是唯一产品依据。直接使用参考图中的产品，保持结构、部件、比例、连接关系和相对位置完全不变。
禁止重新设计、补画、删减、替换或推测任何产品部件。不要用文字重新描述产品的颜色、形状、材质或部件外观。"""

NATIVE_4K_BLOCK = """【原生输出参数】
直接生成原生2160×3840竖屏图，9:16；最大边3840px；宽高均为16px整数倍；总像素8,294,400。禁止先生成小图再放大。"""

VIDEO_VISUAL_BLOCK = """【固定画面规则】
0–15秒全程一个连续镜头，固定中远景，禁止切镜、跳切或转场。
人物全身和产品整体始终完整位于画面安全区。"""

VIDEO_AUDIO_BLOCK = """【固定口播规则】
人物严格交替说话；每句只由指定人物说出。
当前说话者开口时，非当前说话者嘴巴闭合且完全不发声。非当前说话者不得出现口型、气声、附和、笑声或含混发声。
最后一句台词结束后，所有人物闭嘴，不再开口。
只能说逐句台词清单中列出的中文台词；清单之外零人声。禁止旁白、画外音、第三人声、额外人声、哼声、伪语言、乱码语音或任何无法理解的发声。
不得添加任何额外语音；只使用原生中文台词；不得添加背景音乐。"""


def _clean_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not (cleaned := value.strip()):
        raise ValueError(f"{field} 必须是非空文本")
    return cleaned


def _reject_product_appearance(text: str) -> None:
    matched = next((term for term in FORBIDDEN_PRODUCT_APPEARANCE_TERMS if term in text), None)
    if matched is not None:
        raise ValueError(f"产品外观不得推测或描述：{matched}")


def _without_contract_blocks(scene: str, blocks: Sequence[str]) -> str:
    """Allow recompilation without copying a previous contract block twice."""
    for block in blocks:
        scene = scene.replace(block, "")
    return scene.strip()


def compile_image_prompt(base_prompt: str, artifact_name: str) -> str:
    """Append the immutable product-reference and native-4K image requirements."""
    if artifact_name not in IMAGE_ARTIFACTS:
        raise ValueError(f"artifact 不受支持：{artifact_name}")
    scene = _without_contract_blocks(
        _clean_text(base_prompt, "base_prompt"),
        (PRODUCT_REFERENCE_BLOCK, NATIVE_4K_BLOCK),
    )
    _reject_product_appearance(scene)
    if not scene:
        raise ValueError("base_prompt 必须包含场景文本")
    return "\n\n".join((scene, PRODUCT_REFERENCE_BLOCK, NATIVE_4K_BLOCK))


def validate_image_request(
    prompt: str, reference_paths: list[str], width: int, height: int
) -> list[str]:
    """Return image request violations without changing the request values."""
    issues: list[str] = []
    if not reference_paths or not all(isinstance(path, str) and path.strip() for path in reference_paths):
        issues.append("image.reference_missing")
    text = prompt if isinstance(prompt, str) else ""
    try:
        _reject_product_appearance(text)
    except ValueError:
        issues.append("image.product_appearance_forbidden")
    if PRODUCT_REFERENCE_BLOCK not in text:
        issues.append("image.reference_lock_missing")
    if NATIVE_4K_BLOCK not in text:
        issues.append("image.native_4k_missing")
    if (width, height) != IMAGE_SIZE:
        issues.append("image.dimensions_invalid")
    return issues


def _person_ids(people: list[dict[str, object]]) -> tuple[str, str]:
    if len(people) != 2:
        raise ValueError("视频必须有两名不同人物")
    ids: list[str] = []
    for person in people:
        if not isinstance(person, Mapping):
            raise ValueError("视频必须有两名不同人物")
        identifier = person.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("视频必须有两名不同人物")
        ids.append(identifier.strip())
    if len(set(ids)) != 2:
        raise ValueError("视频必须有两名不同人物")
    return ids[0], ids[1]


def _validated_segments(
    segments: list[dict[str, object]], person_ids: tuple[str, str]
) -> list[tuple[float, float, str, str]]:
    if not segments:
        raise ValueError("视频必须有时间段")
    prepared: list[tuple[float, float, str, str]] = []
    previous_end: float | None = None
    previous_speaker: str | None = None
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise ValueError("视频时间段格式无效")
        start, end = segment.get("start"), segment.get("end")
        speaker, dialogue = segment.get("speaker_id"), segment.get("dialogue")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or start < 0
            or end <= start
        ):
            raise ValueError("视频时间段格式无效")
        if previous_end is not None and start < previous_end:
            raise ValueError("视频时间段不得重叠且必须按顺序")
        if not isinstance(speaker, str) or speaker not in person_ids:
            raise ValueError("视频时间段说话人无效")
        if previous_speaker == speaker:
            raise ValueError("视频时间段必须严格交替说话")
        prepared.append((float(start), float(end), speaker, _clean_text(dialogue, "dialogue")))
        previous_end = float(end)
        previous_speaker = speaker
    return prepared


def _format_second(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def compile_video_prompt(
    base_prompt: str,
    people: list[dict[str, object]],
    segments: list[dict[str, object]],
) -> str:
    """Compile a single-shot, two-person Chinese dialogue video prompt."""
    scene = _without_contract_blocks(
        _clean_text(base_prompt, "base_prompt"),
        (VIDEO_VISUAL_BLOCK, VIDEO_AUDIO_BLOCK),
    )
    _reject_product_appearance(scene)
    person_ids = _person_ids(people)
    validated_segments = _validated_segments(segments, person_ids)
    dialogue_lines = [
        f"{_format_second(start)}–{_format_second(end)}秒 {speaker}：{dialogue}"
        for start, end, speaker, dialogue in validated_segments
    ]
    return "\n\n".join((
        scene,
        PRODUCT_REFERENCE_BLOCK,
        VIDEO_VISUAL_BLOCK,
        VIDEO_AUDIO_BLOCK,
        "【逐句台词】\n" + "\n".join(dialogue_lines),
    ))


def validate_video_request(prompt: str, segments: list[dict[str, object]]) -> list[str]:
    """Return stable video contract violations without changing the prompt."""
    text = prompt if isinstance(prompt, str) else ""
    issues: list[str] = []
    if isinstance(prompt, str):
        try:
            _reject_product_appearance(prompt)
        except ValueError:
            issues.append("video.product_appearance_forbidden")
    required_rules = (
        ("产品参考图是唯一产品依据", "video.reference_lock_missing"),
        ("0–15秒", "video.single_shot_missing"),
        ("一个连续镜头", "video.single_shot_missing"),
        ("固定中远景", "video.framing_missing"),
        ("人物全身和产品整体始终完整位于画面安全区", "video.safe_area_missing"),
        ("严格交替说话", "video.speaker_alternation_missing"),
        ("非当前说话者嘴巴闭合且完全不发声", "video.non_speaker_silence_missing"),
        ("最后一句台词结束后，所有人物闭嘴，不再开口", "video.closed_dialogue_missing"),
        ("不得添加任何额外语音", "video.extra_voice_missing"),
        ("清单之外零人声", "video.extra_voice_missing"),
        ("只使用原生中文台词", "video.native_chinese_missing"),
        ("不得添加背景音乐", "video.bgm_missing"),
    )
    for rule, code in required_rules:
        if rule not in text and code not in issues:
            issues.append(code)
    try:
        dialogues = [
            _clean_text(segment.get("dialogue"), "dialogue")
            for segment in segments
            if isinstance(segment, Mapping)
        ]
        if len(dialogues) != len(segments):
            raise ValueError
    except (TypeError, ValueError):
        issues.append("video.segments_invalid")
        return issues
    if any(text.count(dialogue) != 1 for dialogue in dialogues):
        issues.append("video.dialogue_exactly_once")
    return issues
