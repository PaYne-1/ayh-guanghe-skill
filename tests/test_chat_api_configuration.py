import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'skill-package/product-video-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from test_api_chat_config import ChatConfigTests


def test_chat_configuration_is_documented():
    root = SCRIPTS.parent
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    guide = (root / 'references/api-configuration.md').read_text(encoding='utf-8')
    assert 'save_chat_configuration' in skill
    assert 'save_chat_configuration' in guide
    assert '不再强制用户操作隐藏输入框' in guide
    assert '密钥只允许在交互式终端隐藏输入' not in skill
    assert '不得据此覆盖 AutoDL' in guide
