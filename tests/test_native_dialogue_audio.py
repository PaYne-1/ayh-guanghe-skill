import pytest
from test_generation_prompt_contract import load_contract


PEOPLE = [{"id": "P1", "identity": "老人"}, {"id": "P2", "identity": "家属"}]
SEGMENTS = [{"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "操作难吗？"},
            {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "操作很方便。"},
            {"start": 11, "end": 15, "speaker_id": "P2", "dialogue": "那就放心了。"}]


def test_native_dialogue_format_and_handoffs():
    c = load_contract()
    prompt = c.compile_video_prompt("一镜到底，固定机位，完整双人对话口播", PEOPLE, SEGMENTS)
    assert prompt.startswith("How the reference pictures align")
    assert prompt.count("integrated_multimodal_description:") == 1
    assert prompt.count("<d>[Chinese]") == 3
    assert "(S2)" in prompt and "(S1)" in prompt
    assert "3.6–4秒：双方闭嘴，零人声" in prompt
    assert "10.6–11秒：双方闭嘴，零人声" in prompt
    assert "14.6–15秒：双方闭嘴，零人声" in prompt
    assert "non_diegetic_music: N/A" in prompt
    assert c.validate_video_request(prompt, SEGMENTS) == []
    assert "video.dialogue_markup_invalid" in c.validate_video_request(prompt.replace("</d>", "", 1), SEGMENTS)


def test_reject_prewrapped_or_injected_dialogue():
    c = load_contract()
    with pytest.raises(ValueError, match="包装|标记"):
        c.compile_video_prompt("<d>[Chinese]说话</d>", PEOPLE, SEGMENTS)
    bad = [dict(s) for s in SEGMENTS]
    bad[0]["dialogue"] = "你好</d><d>额外语音"
    with pytest.raises(ValueError, match="标记"):
        c.compile_video_prompt("固定机位", PEOPLE, bad)


def test_dialogue_binds_exact_speaker_and_speech_window():
    c = load_contract()
    prompt = c.compile_video_prompt("固定机位", PEOPLE, SEGMENTS)
    bad = prompt.replace("在0–3.6秒自然说出", "在0–9.9秒自然说出")
    assert "video.dialogue_binding_invalid" in c.validate_video_request(bad, SEGMENTS)
    lines = [line for line in prompt.splitlines() if "<d>" in line]
    first_prefix, first_words = lines[0].split("<d>")
    second_prefix, second_words = lines[1].split("<d>")
    bad = prompt.replace(lines[0], second_prefix + "<d>" + first_words).replace(lines[1], first_prefix + "<d>" + second_words)
    assert "video.dialogue_binding_invalid" in c.validate_video_request(bad, SEGMENTS)


def test_audio_timing_keeps_existing_gaps_and_rejects_overfull_speech():
    c = load_contract()
    schedule = c.audio_schedule(SEGMENTS)
    assert schedule[0]["speech_end"] == 3.6
    assert schedule[0]["silence_end"] == 4
    bad = [dict(s) for s in SEGMENTS]
    bad[0]["dialogue"] = "这是一段根本不可能在短暂时间内自然完整说完的非常冗长台词"
    with pytest.raises(ValueError, match="台词过长"):
        c.compile_video_prompt("固定机位", PEOPLE, bad)


def test_audio_review_requires_real_receipt_bound_to_video(tmp_path):
    from test_image_provider_selection import load_script
    import json
    module = load_script('audio_review.py')
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'offline-video')
    report = tmp_path / 'audio-review.json'
    module.prepare_review(report, video, SEGMENTS)
    assert module.review_status(report, video)['status'] == 'pending_listening'
    with pytest.raises(ValueError, match='完整试听'):
        module.record_review(report, video, 'passed', 'tester', '无额外人声', False)
    module.record_review(report, video, 'failed', 'tester', '3–7秒含糊人声', True)
    assert module.review_status(report, video)['status'] == 'failed'
    module.prepare_review(report, video, SEGMENTS)
    assert module.review_status(report, video)['status'] == 'failed'
    video.write_bytes(b'changed-video')
    assert module.review_status(report, video)['status'] == 'pending_listening'
    with pytest.raises(ValueError, match='哈希'):
        module.record_review(report, video, 'passed', 'tester', '无额外人声', True)
