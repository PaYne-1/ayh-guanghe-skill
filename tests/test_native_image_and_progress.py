from test_image_provider_selection import load_script


def test_poll_returns_running_status_without_blocking_loop(monkeypatch):
    runner = load_script('pipeline_runner.py')
    autodl = load_script('autodl_h3.py')
    calls = []
    def query(task_id, **kwargs):
        calls.append((task_id, kwargs))
        return {'data': {'status': 'running'}}
    monkeypatch.setattr(autodl, 'query_task', query)
    monkeypatch.setattr(autodl, 'poll_task', lambda *a, **k: (_ for _ in ()).throw(AssertionError('blocking poll')))
    monkeypatch.setattr(runner, '_load_autodl', lambda: autodl)
    result = runner._poll_item('existing-task', 'fake-key')
    assert len(calls) == 1
    assert calls[0][1]['timeout'] <= 20
    assert result['status'] == 'poll_timeout'
    assert result['remote_status'] == 'running'
    assert result['next_poll_after_seconds'] == 60


def test_native_prompt_does_not_demand_4k():
    contract = load_script('generation_prompt_contract.py')
    prompt = contract.compile_image_prompt('公园散步', '分镜图.png')
    assert '2160' not in prompt
    assert '渠道支持的原生分辨率' in prompt
    assert not contract.validate_image_request(prompt, ['reference.png'], None, None)
    assert not contract.validate_image_request(prompt, ['reference.png'], 1080, 1920)


def test_repeated_run_respects_poll_cooldown_and_never_resubmits(tmp_path, monkeypatch):
    runner = load_script('pipeline_runner.py')
    item = tmp_path / 'V001_test'
    runner._write_task_info(item, {'video_id': 'V001', 'task_id': 'existing', 'retry_count': 0})
    calls = []
    monkeypatch.setattr(runner, '_poll_item', lambda *a: calls.append(a) or {
        'status': 'poll_timeout', 'remote_status': 'running', 'next_poll_after_seconds': 20})
    monkeypatch.setattr(runner, '_submit_item', lambda *a, **k: (_ for _ in ()).throw(AssertionError('resubmit')))
    state = runner.RunnerState(schema_version=1, policy_digest='test', status='GENERATING')
    first = runner._run_autodl_locked(tmp_path, item, state, api_key=None)
    second = runner._run_autodl_locked(tmp_path, item, state, api_key=None)
    assert first['status'] == second['status'] == 'poll_timeout'
    assert len(calls) == 1
    info = runner._task_info(item)
    assert info['task_id'] == 'existing'
    assert info['remote_status'] == 'running'
    assert info['elapsed_seconds'] >= 0


def test_authentication_failure_is_not_reported_as_generating(monkeypatch):
    runner = load_script('pipeline_runner.py')
    autodl = load_script('autodl_h3.py')
    monkeypatch.setattr(autodl, 'query_task', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('AutoDL HTTP 401')))
    monkeypatch.setattr(runner, '_load_autodl', lambda: autodl)
    result = runner._poll_item('existing', 'fake')
    assert result['status'] == 'query_failed'
    assert result['http_status'] == 401


def test_transient_query_failures_stop_after_five_attempts(tmp_path, monkeypatch):
    runner = load_script('pipeline_runner.py')
    item = tmp_path / 'V001_test'
    runner._write_task_info(item, {'video_id': 'V001', 'task_id': 'existing', 'retry_count': 0})
    now = [1000]
    monkeypatch.setattr(runner.time, 'time', lambda: now[0])
    monkeypatch.setattr(runner, '_poll_item', lambda *a: {
        'status': 'poll_timeout', 'remote_status': 'query_unavailable', 'next_poll_after_seconds': 20})
    monkeypatch.setattr(runner, '_submit_item', lambda *a, **k: (_ for _ in ()).throw(AssertionError('resubmit')))
    state = runner.RunnerState(schema_version=1, policy_digest='test', status='GENERATING')
    for index in range(5):
        result = runner._run_autodl_locked(tmp_path, item, state, api_key=None)
        now[0] += 61
    assert result['status'] == 'RECONCILIATION_REQUIRED'
    assert result['task_id'] == 'existing'
    assert runner._task_info(item)['query_error_count'] == 5


def test_first_query_waits_five_minutes_then_one_minute(tmp_path, monkeypatch):
    runner = load_script('pipeline_runner.py')
    item = tmp_path / 'V001_test'
    now = [1000.0]
    monkeypatch.setattr(runner.time, 'time', lambda: now[0])
    runner._persist_submission_response(item, {}, {'task_id': 'existing', 'request_hash': 'fake'})
    calls = []
    monkeypatch.setattr(runner, '_poll_item', lambda *a: calls.append(now[0]) or {
        'status': 'poll_timeout', 'remote_status': 'running'})
    monkeypatch.setattr(runner, '_submit_item', lambda *a, **k: (_ for _ in ()).throw(AssertionError('resubmit')))
    state = runner.RunnerState(schema_version=1, policy_digest='test', status='GENERATING')
    for timestamp, remaining in [(1000, 300), (1299, 1)]:
        now[0] = timestamp
        result = runner._run_autodl_locked(tmp_path, item, state, api_key=None)
        assert result['next_poll_after_seconds'] == remaining
        assert calls == []
    now[0] = 1300
    runner._run_autodl_locked(tmp_path, item, state, api_key=None)
    assert calls == [1300]
    assert runner._task_info(item)['next_poll_at'] == 1360
    now[0] = 1359
    runner._run_autodl_locked(tmp_path, item, state, api_key=None)
    assert calls == [1300]
    now[0] = 1360
    runner._run_autodl_locked(tmp_path, item, state, api_key=None)
    assert calls == [1300, 1360]
