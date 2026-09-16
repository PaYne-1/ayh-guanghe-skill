"""Locked prompt contracts for native-4K images and 15-second videos."""

from __future__ import annotations

import math
import re
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

EXTRA_VOICE_PERMISSION_TERMS = (
    "允许额外人声",
    "允许额外语音",
    "允许旁白",
    "允许画外音",
    "允许第三人声",
    "允许背景音乐",
    "允许BGM",
    "允许哼声",
)

APPEARANCE_DESCRIPTION_TERMS = (
    "黑色",
    "白色",
    "红色",
    "蓝色",
    "灰色",
    "银色",
    "金色",
    "圆形",
    "方形",
    "流线型",
    "弧形",
    "加粗",
    "加宽",
    "加长",
    "加厚",
    "增大",
    "真皮",
    "皮质",
    "金属",
    "塑料",
    "铝合金",
    "碳纤维",
    "改成",
    "变成",
    "换成",
)

PRODUCT_REDESIGN_TERMS = (
    "加装",
    "新增",
    "增加",
    "删减",
    "删除",
    "拆除",
    "替换",
    "改造",
    "重新设计",
    "补画",
)

_COMPONENT_PATTERN = "(?:" + "|".join(
    re.escape(term) for term in FORBIDDEN_PRODUCT_APPEARANCE_TERMS
) + ")"
_APPEARANCE_PATTERN = "(?:" + "|".join(
    re.escape(term) for term in APPEARANCE_DESCRIPTION_TERMS
) + ")"
_REDESIGN_PATTERN = "(?:" + "|".join(
    re.escape(term) for term in PRODUCT_REDESIGN_TERMS
) + ")"
_COMPONENT_SUFFIX_REDESIGN_PATTERN = "(?:" + "|".join(
    re.escape(term) for term in PRODUCT_REDESIGN_TERMS if term != "增加"
) + ")"
_COMPONENT_PREFIX_MODIFIER = re.compile(
    rf"(?:{_APPEARANCE_PATTERN}|{_REDESIGN_PATTERN})\s*(?:的)?\s*{_COMPONENT_PATTERN}"
)
_COMPONENT_SUFFIX_APPEARANCE = re.compile(
    rf"{_COMPONENT_PATTERN}\s*(?:的)?\s*{_APPEARANCE_PATTERN}"
)
_COMPONENT_LINKED_APPEARANCE = re.compile(
    rf"{_COMPONENT_PATTERN}\s*(?:颜色是|采用|使用|做成|制成|上有|带有|具有|是|为)\s*{_APPEARANCE_PATTERN}"
)
_COMPONENT_SUFFIX_REDESIGN = re.compile(
    rf"{_COMPONENT_PATTERN}\s*(?:进行|被)?\s*{_COMPONENT_SUFFIX_REDESIGN_PATTERN}"
)

PRODUCT_REFERENCE_BLOCK = """【产品参考锁定】
上传的产品参考图是唯一产品依据。直接使用参考图中的产品，保持结构、部件、比例、连接关系和相对位置完全不变。
禁止重新设计、补画、删减、替换或推测任何产品部件。不要用文字重新描述产品的颜色、形状、材质或部件外观。"""

NATIVE_4K_BLOCK = """【原生输出参数】
使用渠道支持的原生分辨率生成9:16竖屏图，不强制4K。禁止本地放大、拉伸或裁剪冒充原生输出。"""


def valid_portrait_dimensions(width, height):
    """Allow at most one width pixel of rounding for native 9:16 output."""
    return (type(width) is int and type(height) is int and width > 0 and height > width
            and abs(width * 16 - height * 9) <= 16)

VIDEO_VISUAL_BLOCK = """【固定画面规则】
0–15秒全程一个连续镜头，固定中远景，禁止切镜、跳切或转场。
人物全身和产品整体始终完整位于画面安全区。
分镜图是全程唯一画面基准：在同一张画面上做局部动画，不重新创作画面。
固定机位，背景、构图、景别、光线、人物身份与服装、产品外观和数量全程保持分镜一致；禁止推拉、摇移、环绕、变焦、换景、插入空镜、特写或无关画面。
只允许说话口型、自然微表情和分镜明确指定的产品运动；未指定运动时产品保持原位。运动不得改变产品结构或使主体离开画面。
尾帧仅作为同一画面内动作结束状态，不得引入新场景或新构图；不得根据台词或卖点联想生成其他画面。"""

TAIL_CONTINUITY_BLOCK = """【尾帧画面延续】
以已提供的分镜图为画面基准，保持同一背景、构图、机位、光线、人物身份与服装及产品外观和数量；只表现分镜明确指定动作的结束状态。不得另创场景或改变景别，不额外安排动作。"""

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
    if has_forbidden_product_appearance(text):
        raise ValueError("产品外观不得推测或描述")


def has_forbidden_product_appearance(text: object) -> bool:
    """Reject concrete component appearance or redesign prose, not actions."""
    if not isinstance(text, str):
        return False
    return bool(
        _COMPONENT_PREFIX_MODIFIER.search(text)
        or _COMPONENT_SUFFIX_APPEARANCE.search(text)
        or _COMPONENT_LINKED_APPEARANCE.search(text)
        or _COMPONENT_SUFFIX_REDESIGN.search(text)
    )


def _has_positive_extra_voice_permission(text: str) -> bool:
    """Treat only an affirmative permission as a conflict with closed audio."""
    negators = ("不", "不要", "不得", "禁止", "不可", "严禁")
    for term in EXTRA_VOICE_PERMISSION_TERMS:
        offset = text.find(term)
        while offset != -1:
            prefix = text[max(0, offset - 2):offset]
            if not any(prefix.endswith(negator) for negator in negators):
                return True
            offset = text.find(term, offset + len(term))
    return False


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
        (PRODUCT_REFERENCE_BLOCK, NATIVE_4K_BLOCK, TAIL_CONTINUITY_BLOCK),
    )
    _reject_product_appearance(scene)
    if not scene:
        raise ValueError("base_prompt 必须包含场景文本")
    blocks = [scene, PRODUCT_REFERENCE_BLOCK, NATIVE_4K_BLOCK]
    if artifact_name == "尾帧图.png":
        blocks.append(TAIL_CONTINUITY_BLOCK)
    return "\n\n".join(blocks)


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
        issues.append("image.native_resolution_missing")
    if (width, height) != (None, None) and not valid_portrait_dimensions(width, height):
        issues.append("image.dimensions_invalid")
    return issues


def _person_profiles(people: list[dict[str, object]]) -> tuple[tuple[str, str], dict[str, str]]:
    if len(people) != 2:
        raise ValueError("视频必须有两名不同人物")
    ids: list[str] = []
    identities: dict[str, str] = {}
    for person in people:
        if not isinstance(person, Mapping):
            raise ValueError("视频必须有两名不同人物")
        identifier = person.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("视频必须有两名不同人物")
        identity = person.get("identity")
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("视频人物必须包含身份映射")
        identifier = identifier.strip()
        ids.append(identifier)
        identities[identifier] = identity.strip()
    if len(set(ids)) != 2:
        raise ValueError("视频必须有两名不同人物")
    return (ids[0], ids[1]), identities


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
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or start < 0
            or end > 15
            or end <= start
        ):
            raise ValueError("视频时间段必须位于0–15秒且满足 start < end")
        if previous_end is not None and start < previous_end:
            raise ValueError("视频时间段不得重叠且必须按顺序")
        if not isinstance(speaker, str) or speaker not in person_ids:
            raise ValueError("视频时间段说话人无效")
        if previous_speaker == speaker:
            raise ValueError("视频时间段必须严格交替说话")
        cleaned_dialogue = _clean_text(dialogue, "dialogue")
        if any(mark in cleaned_dialogue for mark in ("<", ">", "\n", "\r")):
            raise ValueError("台词只能包含实际口播文字，不得包含语音标记或换行")
        if any(existing[3] == cleaned_dialogue for existing in prepared):
            raise ValueError("视频台词不得重复")
        prepared.append((float(start), float(end), speaker, cleaned_dialogue))
        previous_end = float(end)
        previous_speaker = speaker
    return prepared


def _format_second(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def audio_schedule(segments):
    ids = tuple(sorted({s["speaker_id"] for s in segments}))
    prepared = _validated_segments(segments, ids)
    result = []
    for index, (start, end, speaker, dialogue) in enumerate(prepared):
        next_start = prepared[index + 1][0] if index + 1 < len(prepared) else 15.0
        speech_end = round(min(end, next_start - 0.4), 3)
        if speech_end <= start:
            raise ValueError("台词时间段不足以保留交接静默")
        if len(re.findall(r"[\u4e00-\u9fff]", dialogue)) > (speech_end - start) * 5 + 1e-6:
            raise ValueError("台词过长，请先精简内容，不得压缩交接静默或加速抢读")
        result.append({"start": start, "end": end, "speaker_id": speaker,
                       "speech_end": speech_end, "silence_end": next_start})
    return result


def _silence_line(row):
    return (f'{_format_second(row["speech_end"])}–{_format_second(row["silence_end"])}秒：双方闭嘴，零人声；'
            "不出现气声、含混语音或附和。")


def visual_instruction_issues(text: str, segments=(), motion_record=None) -> list[str]:
    """Conservative lexical checks; not a claim of full semantic verification."""
    scene = _without_contract_blocks(text, (PRODUCT_REFERENCE_BLOCK, VIDEO_VISUAL_BLOCK, VIDEO_AUDIO_BLOCK))
    scene = scene.replace("integrated_multimodal_description: [Shot 1] ", "")
    for segment in segments:
        if isinstance(segment, Mapping) and isinstance(segment.get("dialogue"), str):
            # Exclude only a complete generated dialogue line, never matching scene prose.
            line_pattern = (r"(?m)^\d+(?:\.\d+)?–\d+(?:\.\d+)?秒 speaker_id=[^（\n]+（[^）\n]+） \(S\d+\) [^\n<]+<d>\[Chinese\]"
                            + re.escape(segment["dialogue"]) + r"</d>$")
            scene = re.sub(line_pattern, "", scene)
    allowed = []
    if motion_record is not None:
        if (not isinstance(motion_record, Mapping)
                or motion_record.get("confirmed_by_user") is not True
                or not isinstance(motion_record.get("motion_clauses"), list)
                or not motion_record["motion_clauses"]
                or not all(isinstance(v, str) and v.strip() for v in motion_record["motion_clauses"])):
            return ["video.motion_record_invalid"]
        allowed = [v.strip() for v in motion_record["motion_clauses"]]
    camera = re.compile(r"运镜|推拉|摇移|环绕|变焦|切镜|跳切|转场|换景|切换场景|插入.*(?:空镜|画面)|(?:镜头|机位).{0,8}(?P<camera_action>推进|拉近|拉远|移动|转动)")
    motion = re.compile(r"移动|前进|后退|行驶|驶入|驶出|转弯|旋转|加速|减速|滚动|运动|折叠|展开")
    issues = []
    for clause in re.split(r"[。；;，,\n]|但是|不过|然而|但|却|而是|然后|随后|并且|并|同时", scene):
        clause = clause.strip()
        if not clause:
            continue
        negated = re.search(r"禁止|不得|不要|不允许|不可|严禁|不做|不进行|不能|避免|(?:不|无)(?=运镜|推拉|摇移|环绕|变焦|切镜|跳切|转场|换景|移动|前进|后退|行驶|运动)", clause)
        double_negative = re.search(r"(?:不|不要|不得)(?:再)?(?:禁止|限制|避免)", clause)
        # A negation applies only to the verbs after it, not preceding commands.
        def affirmative(pattern):
            return any(double_negative or not negated or
                       (m.start("camera_action") if m.lastgroup == "camera_action" else m.start()) < negated.start()
                       for m in pattern.finditer(clause))
        if affirmative(camera) and "video.visual_conflict" not in issues:
            issues.append("video.visual_conflict")
        if affirmative(motion) and clause not in allowed and "video.product_motion_unconfirmed" not in issues:
            issues.append("video.product_motion_unconfirmed")
    return issues


def compile_video_prompt(
    base_prompt: str,
    people: list[dict[str, object]],
    segments: list[dict[str, object]],
    motion_record: dict | None = None,
) -> str:
    """Compile a single-shot, two-person Chinese dialogue video prompt."""
    scene = _without_contract_blocks(
        _clean_text(base_prompt, "base_prompt"),
        (PRODUCT_REFERENCE_BLOCK, VIDEO_VISUAL_BLOCK, VIDEO_AUDIO_BLOCK),
    )
    if any(marker in scene for marker in ("<d", "</d", "integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")):
        raise ValueError("video_prompt不得预先包装H3语音标记，由编译器统一包装一次")
    _reject_product_appearance(scene)
    conflicts = visual_instruction_issues(scene, (), motion_record)
    if conflicts:
        raise ValueError("视频指令冲突：" + ",".join(conflicts))
    person_ids, person_identities = _person_profiles(people)
    validated_segments = _validated_segments(segments, person_ids)
    schedule = audio_schedule(segments)
    speaker_labels = {identifier: f"S{index + 1}" for index, identifier in enumerate(sorted(person_ids))}
    dialogue_lines = []
    if schedule[0]["start"] > 0:
        dialogue_lines.append(f'0–{_format_second(schedule[0]["start"])}秒：双方闭嘴，零人声。')
    for (start, end, speaker, dialogue), row in zip(validated_segments, schedule):
        dialogue_lines.append(
            f'{_format_second(start)}–{_format_second(end)}秒 speaker_id={speaker}（{person_identities[speaker]}） ({speaker_labels[speaker]}) '
            f'在{_format_second(start)}–{_format_second(row["speech_end"])}秒自然说出：<d>[Chinese]{dialogue}</d>')
        dialogue_lines.append(_silence_line(row))
    return "\n\n".join((
        "How the reference pictures align with the target video: Picture 1 anchors 0.00 seconds; Picture 2 anchors 15.00 seconds. Both belong to Shot 1.",
        "integrated_multimodal_description: [Shot 1] " + scene,
        PRODUCT_REFERENCE_BLOCK,
        VIDEO_VISUAL_BLOCK,
        VIDEO_AUDIO_BLOCK,
        "【逐句台词】\n" + "\n".join(dialogue_lines),
        "overall_soundscape: Quiet non-vocal room tone only. Speech pauses contain no human vocalization, breathing, laughter or babble.",
        "non_diegetic_music: N/A",
    ))


def compile_compact_video_prompt(base_prompt, people, segments, motion_record=None):
    """Opt-in trial: validate source normally, then render one canonical short form."""
    standard = compile_video_prompt(base_prompt, people, segments, motion_record)
    issues = validate_video_request(standard, segments, motion_record)
    if issues:
        raise ValueError("视频合同校验失败：" + ",".join(issues))
    scene = _without_contract_blocks(base_prompt.strip(),
        (PRODUCT_REFERENCE_BLOCK, VIDEO_VISUAL_BLOCK, VIDEO_AUDIO_BLOCK))
    ids, identities = _person_profiles(people)
    labels = {identifier: f"S{index + 1}" for index, identifier in enumerate(sorted(ids))}
    roles = "；".join(f"({labels[i]})是{identities[i]}，使用与身份一致的固定普通话声线" for i in sorted(ids))
    lines = []
    schedule = audio_schedule(segments)
    if schedule[0]['start'] > 0:
        lines.append(f"0–{_format_second(schedule[0]['start'])}秒双方闭嘴，无人声。")
    for row, segment in zip(schedule, segments):
        lines.append(f"{_format_second(row['start'])}–{_format_second(row['speech_end'])}秒 "
                     f"({labels[row['speaker_id']]})自然说：<d>[Chinese]{segment['dialogue']}</d>")
        lines.append(f"{_format_second(row['speech_end'])}–{_format_second(row['silence_end'])}秒双方闭嘴，无人声。")
    return "\n\n".join((
        "How the reference pictures align with the target video: Picture 1 is the first frame; Picture 2 is the final frame of the same shot.",
        "integrated_multimodal_description: [Shot 1] " + scene,
        "产品参考图是唯一产品依据；产品结构、部件、比例和外观保持参考图不变，不重新设计。"
        "分镜图是全程唯一画面基准；0–15秒一镜到底，固定机位、固定中远景。"
        "背景、构图、光线、人物身份与服装、产品数量保持不变，人物全身和产品整体始终完整位于画面安全区。"
        "只允许说话口型、自然微表情及已确认的产品运动；未指定则保持原位。"
        "尾帧仅延续同一画面的动作结束状态，不切镜、不运镜、不换景。",
        roles + "。完整双人对话口播；依次只说下列三句，台词与口型同步。"
        "非当前说话者嘴巴闭合且完全不发声；清单之外零人声，无旁白、无背景音乐。",
        "\n".join(lines),
        "overall_soundscape: Only the specified Chinese dialogue, with silence between turns.",
        "non_diegetic_music: N/A",
    ))


def validate_compact_video_request(prompt, base_prompt, people, segments, motion_record=None):
    """Exact recompilation rejects added speech, altered timing and missing locks."""
    try:
        expected = compile_compact_video_prompt(base_prompt, people, segments, motion_record)
    except (ValueError, TypeError, KeyError):
        return ["video.compact_source_invalid"]
    return [] if prompt == expected else ["video.compact_request_mismatch"]


def compile_reference_wide_video_prompt(base_prompt, people, segments, motion_record=None):
    """Portable version of the user-accepted wide-view/turn-bound experiment.

    Input safety is checked before rendering; output wording is an instruction,
    not a claim that reference-image APIs enforce camera or endpoint constraints.
    """
    standard = compile_video_prompt(base_prompt, people, segments, motion_record)
    issues = validate_video_request(standard, segments, motion_record)
    if issues:
        raise ValueError('视频合同校验失败：' + ','.join(issues))
    ids, identities = _person_profiles(people)
    labels = {identifier: f'S{index + 1}' for index, identifier in enumerate(sorted(ids))}
    roles, voices = {}, []
    for person in people:
        identifier = person['id'].strip()
        role = _clean_text(person.get('video_role', identities[identifier]), 'video_role')
        voice = _clean_text(person.get('video_voice', 'a consistent natural Mandarin voice matching the person in the reference'), 'video_voice')
        for value in (role, voice):
            if (any(mark in value for mark in ('<', '>', '\n', '\r', '[Shot', 'integrated_multimodal_description:', 'overall_soundscape:', 'non_diegetic_music:'))
                    or _has_positive_extra_voice_permission(value)
                    or any(s['dialogue'] in value for s in segments)):
                raise ValueError('人物映射只填写身份或声线，不得包含台词、指令包装或额外人声')
            _reject_product_appearance(value)
            if visual_instruction_issues(value, (), None):
                raise ValueError('人物映射不得夹带运镜或产品动作指令')
        roles[identifier] = role
        voices.append(f'{role} ({labels[identifier]}) uses {voice}.')
    scene = _without_contract_blocks(base_prompt.strip(),
        (PRODUCT_REFERENCE_BLOCK, VIDEO_VISUAL_BLOCK, VIDEO_AUDIO_BLOCK))
    # Source already includes any authorized motion; do not invent or duplicate it.
    motion = ('Any specified product movement stays within the wide composition with the complete product visible. '
              if motion_record else 'The product remains in its reference position. ')
    lines = []
    schedule = audio_schedule(segments)
    if schedule[0]['start'] > 0:
        lines.append(f"0-{schedule[0]['start']:g}s: Both people have closed lips and remain silent.")
    for row, segment in zip(schedule, segments):
        speaker = segment['speaker_id']
        listener = next(identifier for identifier in ids if identifier != speaker)
        lines.append(f"{row['start']:g}-{row['speech_end']:g}s: {roles[listener]} keeps their lips closed and listens silently. "
                     f"{roles[speaker]} ({labels[speaker]}) says once: <d>[Chinese]{segment['dialogue']}</d>")
        lines.append(f"{row['speech_end']:g}-{row['silence_end']:g}s: Both people have closed lips and remain silent.")
    prompt = '\n\n'.join((
        'Pictures 1 and 2 are composition references for the same continuous scene. '
        'Use Picture 1 as the visual layout throughout the video; Picture 2 reinforces the same people, product and wide composition.',
        'integrated_multimodal_description: [Shot 1] 一镜到底，固定机位，完整双人对话口播。'
        'A single uninterrupted wide master shot lasts for the entire 15 seconds. '
        'The camera observes the complete two-person conversation from one fixed distant position. '
        'Both people are visible head to toe, and the complete product silhouette remains inside the picture '
        'with generous space below and on both sides at every moment. '
        'The field of view and subject scale stay constant during every speaking turn and pause. '
        'The uploaded reference is the sole product source. Preserve its exact structure, parts and proportions. '
        'Preserve the reference background, lighting, clothing, people and product throughout. '
        + motion + scene + ' Only the active speaker moves their lips. ' + ' '.join(voices),
        '\n'.join(lines),
        'overall_soundscape: The two voices alternate. No overlapping speech, narrator, additional utterances or music.',
        'non_diegetic_music: N/A',
    ))
    if any(prompt.count(segment['dialogue']) != 1 for segment in segments):
        raise ValueError('台词只能在对应语音标签中出现一次')
    return prompt


def validate_reference_wide_video_request(prompt, base_prompt, people, segments, motion_record=None):
    try:
        expected = compile_reference_wide_video_prompt(base_prompt, people, segments, motion_record)
    except (ValueError, TypeError, KeyError):
        return ['video.reference_wide_source_invalid']
    return [] if prompt == expected else ['video.reference_wide_request_mismatch']


def validate_video_request(prompt: str, segments: list[dict[str, object]], motion_record=None) -> list[str]:
    """Return stable video contract violations without changing the prompt."""
    text = prompt if isinstance(prompt, str) else ""
    issues: list[str] = []
    issues.extend(visual_instruction_issues(text, segments, motion_record))
    if isinstance(prompt, str):
        try:
            _reject_product_appearance(prompt)
        except ValueError:
            issues.append("video.product_appearance_forbidden")
        if _has_positive_extra_voice_permission(prompt):
            issues.append("video.extra_voice_permission_forbidden")
    required_rules = (
        ("产品参考图是唯一产品依据", "video.reference_lock_missing"),
        ("0–15秒", "video.single_shot_missing"),
        ("一个连续镜头", "video.single_shot_missing"),
        ("固定中远景", "video.framing_missing"),
        ("固定机位", "video.framing_missing"),
        ("分镜图是全程唯一画面基准", "video.storyboard_lock_missing"),
        ("只允许说话口型、自然微表情和分镜明确指定的产品运动", "video.motion_scope_missing"),
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
    if (re.findall(r"<d>\[Chinese\]([^<>\n]+)</d>", text) != dialogues
            or text.count("<d>") != len(dialogues) or text.count("</d>") != len(dialogues)):
        issues.append("video.dialogue_markup_invalid")
    if any(text.count(field) != 1 for field in ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")):
        issues.append("video.audio_structure_invalid")
    try:
        speaker_labels = {identifier: f"S{index + 1}" for index, identifier in enumerate(sorted({s["speaker_id"] for s in segments}))}
        for row, segment in zip(audio_schedule(segments), segments):
            binding_pattern = (
                r"(?m)^" + re.escape(f'{_format_second(row["start"])}–{_format_second(row["end"])}秒 speaker_id={row["speaker_id"]}（')
                + r"[^）\n]+） " + re.escape(f'({speaker_labels[row["speaker_id"]]}) 在{_format_second(row["start"])}–{_format_second(row["speech_end"])}秒自然说出：<d>[Chinese]{segment["dialogue"]}</d>') + r"$")
            if not re.search(binding_pattern, text):
                issues.append("video.dialogue_binding_invalid")
                break
            if _silence_line(row) not in text:
                issues.append("video.handoff_silence_missing")
                break
    except (ValueError, KeyError, TypeError):
        issues.append("video.audio_timing_invalid")
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        start, end = segment.get("start"), segment.get("end")
        speaker = segment.get("speaker_id")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or not isinstance(speaker, str)
        ):
            continue
        binding = (
            f"{_format_second(float(start))}–{_format_second(float(end))}秒 "
            f"speaker_id={speaker}（"
        )
        speaker_ids = sorted({s.get("speaker_id") for s in segments if isinstance(s, Mapping) and isinstance(s.get("speaker_id"), str)})
        label = f"S{speaker_ids.index(speaker) + 1}"
        if not re.search(re.escape(binding) + r"[^）\n]+） \(" + label + r"\)", text):
            issues.append("video.speaker_identity_missing")
            break
    return issues
