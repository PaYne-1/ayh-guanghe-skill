import importlib.util
import json
from pathlib import Path
import pytest


def client():
    path = Path(__file__).resolve().parents[1] / 'skill-package/product-video-pipeline/scripts/autodl_h3.py'
    spec = importlib.util.spec_from_file_location('h3_transport_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_file(tmp_path):
    payload = {'prompt': '一镜到底，固定机位，完整双人对话口播。', 'duration': 15,
               'resolution': '768p竖', 'seed': 123, 'first_frame': 'private-image-A',
               'last_frame': 'private-image-B'}
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path, payload


def test_preview_distinguishes_reference_from_endpoint_binding(tmp_path):
    m = client()
    path, payload = request_file(tmp_path)
    preview = m.submit_payload(path, dry_run=True)
    evidence = preview['transport_evidence']
    assert evidence['image_binding'] == 'reference_images_prompt_only'
    assert evidence['camera_lock_guaranteed'] is False
    assert evidence['server_prompt_rewrite'] == 'unknown'
    assert preview['payload']['prompt'] == payload['prompt']
    assert preview['payload']['ref_image_1'] == payload['last_frame']
    assert 'private-image' not in json.dumps(evidence)


def test_legacy_ten_second_endpoint_rejects_15_seconds(tmp_path):
    m = client()
    path, _ = request_file(tmp_path)
    with pytest.raises(ValueError, match='10'):
        m.submit_payload(path, dry_run=True, workflow_id='minimax_h3_lightx2v')


def test_evidence_saved_before_post_without_secrets(tmp_path, monkeypatch):
    m = client()
    path, payload = request_file(tmp_path)
    response_path = tmp_path / 'response.json'
    evidence_path = tmp_path / 'response.request-evidence.json'
    def post(method, url, key, scheme, wire, timeout):
        assert evidence_path.exists()
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        assert evidence['request_hash'] == m._request_hash(wire)
        assert wire['prompt'] == payload['prompt']
        assert key not in evidence_path.read_text(encoding='utf-8')
        return {'task_id': 'test-only'}
    monkeypatch.setattr(m, '_json_request', post)
    assert m.submit_payload(path, api_key='SECRET-TEST-KEY', confirm_paid=True,
                            response_path=response_path)['task_id'] == 'test-only'
