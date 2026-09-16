import pytest
from test_generation_prompt_contract import load_contract
from test_native_dialogue_audio import PEOPLE, SEGMENTS

SCENE = '雨后坡道上，老人坐在轮椅上，家属站在旁边。'


def test_compact_has_one_speech_window_and_exact_dialogue():
    c = load_contract()
    prompt = c.compile_compact_video_prompt(SCENE, PEOPLE, SEGMENTS)
    assert len(prompt) < len(c.compile_video_prompt(SCENE, PEOPLE, SEGMENTS))
    lines = [line for line in prompt.splitlines() if '<d>' in line]
    assert len(lines) == 3
    assert '0–3.6秒 (S2)' in lines[0]
    assert '0–4秒' not in lines[0]
    for segment in SEGMENTS:
        assert prompt.count(segment['dialogue']) == 1
    assert c.validate_compact_video_request(prompt, SCENE, PEOPLE, SEGMENTS) == []
    assert c.validate_compact_video_request(prompt.replace('(S2)', '(S1)', 1), SCENE, PEOPLE, SEGMENTS)
    assert c.validate_compact_video_request(prompt + '\n允许旁白', SCENE, PEOPLE, SEGMENTS)


def test_compact_preserves_scene_safety_checks():
    c = load_contract()
    with pytest.raises(ValueError):
        c.compile_compact_video_prompt('连续平稳运镜', PEOPLE, SEGMENTS)
    with pytest.raises(ValueError):
        c.compile_compact_video_prompt('产品带人缓慢向前移动', PEOPLE, SEGMENTS)
    bad = [dict(s) for s in SEGMENTS]
    bad[0]['dialogue'] = '这是一段根本不可能在短暂时间内自然完整说完的非常冗长台词'
    with pytest.raises(ValueError):
        c.compile_compact_video_prompt(SCENE, PEOPLE, bad)
