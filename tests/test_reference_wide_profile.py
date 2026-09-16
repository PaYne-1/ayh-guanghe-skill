import copy
import json
import pytest
from test_generation_prompt_contract import load_contract
from test_native_dialogue_audio import PEOPLE, SEGMENTS
from test_pipeline_runtime_contract import setup_batch, approve, accept_content, next_image, write


def profiles():
    people = copy.deepcopy(PEOPLE)
    people[0].update(video_role='The elderly rider seated on the right', video_voice='a warm older Mandarin voice')
    people[1].update(video_role='The younger companion standing on the left', video_voice='a brighter younger Mandarin voice')
    return people


def test_reference_wide_has_exact_turns_and_listener_binding():
    c = load_contract()
    assert hasattr(c, 'compile_reference_wide_video_prompt')
    prompt = c.compile_reference_wide_video_prompt('固定机位', profiles(), SEGMENTS)
    assert 'composition references' in prompt and 'first frame' not in prompt
    assert 'wide master shot' in prompt
    assert '依次' not in prompt and '下列三句' not in prompt
    assert prompt.count('[Shot 1]') == 1
    spoken = [line for line in prompt.splitlines() if '<d>' in line]
    assert 'rider seated on the right keeps their lips closed' in spoken[0]
    assert 'companion standing on the left (S2) says once:' in spoken[0]
    assert 'rider seated on the right (S1) says once:' in spoken[1]
    assert '3.6-4s: Both people have closed lips' in prompt
    for segment in SEGMENTS:
        assert prompt.count(segment['dialogue']) == 1
    assert c.validate_reference_wide_video_request(prompt, '固定机位', profiles(), SEGMENTS) == []
    assert c.validate_reference_wide_video_request(prompt.replace('(S2)', '(S1)', 1), '固定机位', profiles(), SEGMENTS)


def test_profile_does_not_invent_roles_motion_or_fixed_seed():
    c = load_contract()
    assert hasattr(c, 'compile_reference_wide_video_prompt')
    prompt = c.compile_reference_wide_video_prompt('固定机位', PEOPLE, SEGMENTS)
    assert 'seated on the right' not in prompt
    assert '2026091606' not in prompt
    assert 'product remains in its reference position' in prompt
    with pytest.raises(ValueError):
        c.compile_reference_wide_video_prompt('连续平稳运镜', PEOPLE, SEGMENTS)
    with pytest.raises(ValueError):
        c.compile_reference_wide_video_prompt('产品带人缓慢向前移动', PEOPLE, SEGMENTS)


def test_role_metadata_cannot_inject_dialogue():
    c = load_contract()
    assert hasattr(c, 'compile_reference_wide_video_prompt')
    people = profiles()
    people[0]['video_role'] = '<d>[Chinese]额外台词</d>'
    with pytest.raises(ValueError):
        c.compile_reference_wide_video_prompt('固定机位', people, SEGMENTS)


@pytest.mark.parametrize('field', ['video_role', 'video_voice'])
@pytest.mark.parametrize('instruction', ['连续平稳运镜', '产品带人缓慢向前移动'])
def test_role_metadata_cannot_bypass_visual_contract(field, instruction):
    c = load_contract()
    people = profiles()
    people[0][field] = instruction
    with pytest.raises(ValueError):
        c.compile_reference_wide_video_prompt('固定机位', people, SEGMENTS)


def test_runner_uses_profile_and_keeps_binding_immutable(setup_batch, capsys):
    runner, policy, batch, items, state = setup_batch
    action = approve(setup_batch, capsys)
    accept_content(setup_batch, action, capsys)
    path = items[0] / '_工作文件/生成过程/策划内容.json'
    content = json.loads(path.read_text(encoding='utf-8'))
    content['video_prompt_style'] = 'reference_wide_v1'
    content['people'] = profiles()
    write(path, content)
    for index in range(6):
        next_image(setup_batch, capsys, (index * 20, 70, 120))
    state = runner.load_or_create_state(batch, policy)
    payload_path = runner.prepare_payload(batch, items[0], state)
    payload = json.loads(payload_path.read_text(encoding='utf-8'))
    assert 'wide master shot' in payload['prompt']
    before = payload_path.read_bytes()
    runner.prepare_payload(batch, items[0], state)
    assert before == payload_path.read_bytes()
    content['video_prompt'] = '固定机位。不同场景。'
    write(path, content)
    with pytest.raises(PermissionError):
        runner.prepare_payload(batch, items[0], state)


def test_new_content_action_recommends_wide_profile(setup_batch, capsys):
    action = approve(setup_batch, capsys)
    from pathlib import Path
    brief = json.loads(Path(action['prompt_path']).read_text(encoding='utf-8'))
    assert brief.get('video_prompt_style') == 'reference_wide_v1'
