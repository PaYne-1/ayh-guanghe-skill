import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill-package/product-video-pipeline/scripts'))
import api_chat_config
import api_config


def test_parse_chinese_credentials_without_cross_assignment():
    payload = api_chat_config.parse_chat_text(
        'AUTODL\\_API\\_KEY：video-test\n第三方生图 API：image-test\n'
        '第三方生图 模型：image-model\n第三方文本生成 API：text-test\n'
        '第三方文本生成 模型：text-model')
    assert payload['autodl']['key'] == 'video-test'
    assert payload['image']['key'] == 'image-test'
    assert payload['text']['key'] == 'text-test'
    assert payload['text']['model'] == 'text-model'


def test_raw_chat_uses_saved_connection():
    store = api_config.MemoryStore({
        'PRODUCT_VIDEO_IMAGE_API_PROVIDER': 'Example',
        'PRODUCT_VIDEO_IMAGE_API_BASE_URL': 'https://example.com',
        'PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN': '1',
    })
    api_chat_config.save_chat_configuration('第三方生图 API：fake-secret\n第三方生图 模型：new-image', store)
    assert store.get('PRODUCT_VIDEO_IMAGE_API_MODEL') == 'new-image'


def test_startup_template_complete():
    import startup_gate
    result = startup_gate.render()
    assert all(heading in result for heading in ('你需要提供的内容', '本次配置明细', '请你回复'))
    assert 'frame_*.png' not in result


def test_init_without_confirmation_does_not_initialize(monkeypatch):
    import workflow_cli
    called = []
    monkeypatch.setattr(workflow_cli, 'initialize_batch', lambda **kw: called.append(kw))
    code = workflow_cli.main(['init', '--product-dir', 'missing', '--product-name', 'test',
        '--selling-point', 'test', '--total', '1', '--mode', 'auto', '--max-budget', '1',
        '--cover-reference-dir', 'missing', '--image-provider', 'codex'])
    assert code != 0
    assert not called


def test_matching_receipt_and_changed_budget(tmp_path):
    import startup_gate
    import json
    fields = dict(product_dir=str(tmp_path), product_name='test', selling_points=['stable'],
                  total=1, mode='auto', resolution='768P', max_budget='10',
                  cover_reference_dir=str(tmp_path), image_provider='codex')
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(dict(confirmed=True, user_reply='以上配置确认', fields=fields)), encoding='utf-8')
    startup_gate.require_confirmation(receipt, fields)
    with pytest.raises(ValueError, match='max_budget'):
        startup_gate.require_confirmation(receipt, dict(fields, max_budget='500'))


def test_unconfirmed_record_rejected():
    import startup_gate
    with pytest.raises(ValueError):
        startup_gate.validate_record(dict(confirmed=False, user_reply='启动'))


def test_original_connection_format():
    result = api_chat_config.parse_chat_text('连接信息：{"key":"fake","url":"example.com"}\n第三方生图模型选择：image\n第三方文本生成模型选择：text')
    assert result['connection']['key'] == 'fake'
    assert result['image']['model'] == 'image'
    assert result['text']['model'] == 'text'


def test_boolean_user_reply_rejected():
    import startup_gate
    with pytest.raises(ValueError):
        startup_gate.validate_record(dict(confirmed=True, user_reply=True))


def test_shared_key_two_models_no_price():
    store = api_config.MemoryStore({'PRODUCT_VIDEO_IMAGE_API_PROVIDER': 'Example',
        'PRODUCT_VIDEO_IMAGE_API_BASE_URL': 'https://example.com'})
    result = api_chat_config.save_chat_configuration('第三方 API：shared-fake\n第三方生图 模型：image\n第三方文本生成 模型：text', store)
    assert store.get('PRODUCT_VIDEO_IMAGE_API_KEY') == store.get('PRODUCT_VIDEO_TEXT_API_KEY') == 'shared-fake'
    assert store.get('PRODUCT_VIDEO_TEXT_API_BASE_URL') == 'https://example.com'
    assert result['categories']['image']['status'] == '已配置'
    assert result['categories']['image']['pricing_status'] == '未核实'


def test_conflicting_shared_keys_rejected_without_writes():
    store = api_config.MemoryStore()
    with pytest.raises(api_config.ConfigurationInputError):
        api_chat_config.save_chat_configuration('第三方生图 API：first-fake\n第三方文本生成 API：second-fake', store)
    assert not store.values


def test_missing_api_connection_never_writes_or_echoes():
    store = api_config.MemoryStore()
    with pytest.raises(api_config.ConfigurationInputError) as error:
        api_chat_config.save_chat_configuration('第三方生图 API：fake-secret\n第三方生图 模型：new-image', store)
    assert not store.values
    assert 'fake-secret' not in str(error.value)


@pytest.mark.parametrize('message', ['第三方 API：first\n第三方 API：second',
    '连接信息：{"key":"first"}\n第三方 API：second',
    '第三方 API：first\n连接信息：{"key":"second"}'])
def test_duplicate_shared_connection_conflicts(message):
    with pytest.raises(api_config.ConfigurationInputError):
        api_chat_config.parse_chat_text(message)


def test_changed_model_invalidates_saved_price():
    store = api_config.MemoryStore({
        'PRODUCT_VIDEO_IMAGE_API_PROVIDER': 'Example',
        'PRODUCT_VIDEO_IMAGE_API_BASE_URL': 'https://example.com',
        'PRODUCT_VIDEO_IMAGE_API_KEY': 'fake',
        'PRODUCT_VIDEO_IMAGE_API_MODEL': 'old-model',
        'PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN': '1',
    })
    result = api_chat_config.save_chat_configuration('第三方生图 模型：new-model', store)
    assert not store.get('PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN')
    assert result['categories']['image']['pricing_status'] == '未核实'


def test_runtime_connection_does_not_require_image_price():
    store = api_config.MemoryStore({
        'PRODUCT_VIDEO_IMAGE_API_PROVIDER': 'Example',
        'PRODUCT_VIDEO_IMAGE_API_BASE_URL': 'https://example.com',
        'PRODUCT_VIDEO_IMAGE_API_KEY': 'fake',
        'PRODUCT_VIDEO_IMAGE_API_MODEL': 'model',
    })
    config = api_config.image_api_runtime_config(store)
    assert 'unit_price_yuan' not in config
    assert config['model'] == 'model'
