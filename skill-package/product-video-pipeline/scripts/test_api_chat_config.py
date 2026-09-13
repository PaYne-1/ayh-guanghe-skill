import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import api_config


class ChatConfigTests(unittest.TestCase):
    def setUp(self):
        self.store = api_config.MemoryStore({'AUTODL_API_KEY': 'unchanged'})
        self.payload = {
            'connection': {'_type': 'newapi_channel_conn', 'key': 'test-only-secret-1234', 'url': 'example.com'},
            'provider': 'Example',
            'image': {'model': 'image-test', 'unit_price_yuan': '0.5'},
            'text': {'model': 'text-test'},
        }

    def module(self):
        import api_chat_config
        return api_chat_config

    def test_both_categories_persist_and_mask(self):
        result = self.module().save_chat_configuration(self.payload, self.store)
        self.assertEqual(self.store.get('PRODUCT_VIDEO_IMAGE_API_KEY'), 'test-only-secret-1234')
        self.assertEqual(self.store.get('PRODUCT_VIDEO_TEXT_API_BASE_URL'), 'https://example.com')
        self.assertEqual(self.store.get('AUTODL_API_KEY'), 'unchanged')
        self.assertNotIn('test-only-secret-1234', json.dumps(result))
        self.assertIn('1234', json.dumps(result))

    def test_missing_price_writes_nothing(self):
        del self.payload['image']['unit_price_yuan']
        with self.assertRaises(api_config.ConfigurationInputError):
            self.module().save_chat_configuration(self.payload, self.store)
        self.assertEqual(dict(self.store.values), {'AUTODL_API_KEY': 'unchanged'})

    def test_invalid_url_writes_nothing(self):
        self.payload['connection']['url'] = 'http://example.com'
        with self.assertRaises(api_config.ConfigurationInputError):
            self.module().save_chat_configuration(self.payload, self.store)
        self.assertEqual(len(self.store.values), 1)

    def test_stdin_cli_does_not_prompt(self):
        module = self.module()
        output = io.StringIO()
        with patch.object(module, 'WindowsUserEnvironmentStore', return_value=self.store), patch('sys.stdin', io.StringIO(json.dumps(self.payload))), redirect_stdout(output):
            self.assertEqual(module.main(), 0)
        self.assertNotIn('test-only-secret-1234', output.getvalue())

    def test_bad_json_does_not_echo_secret(self):
        module = self.module()
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO('{test-only-secret-1234')), redirect_stdout(output):
            self.assertEqual(module.main(), 1)
        self.assertNotIn('test-only-secret-1234', output.getvalue())

    def test_readback_failure_rolls_back(self):
        class BrokenStore(api_config.MemoryStore):
            def set_many(self, values):
                super().set_many(values)
                if values.get('PRODUCT_VIDEO_TEXT_API_MODEL'):
                    self.values['PRODUCT_VIDEO_TEXT_API_MODEL'] = 'wrong'
        store = BrokenStore({'AUTODL_API_KEY': 'unchanged'})
        with self.assertRaises(RuntimeError):
            self.module().save_chat_configuration(self.payload, store)
        self.assertEqual(dict(store.values), {'AUTODL_API_KEY': 'unchanged'})

    def test_status_failure_rolls_back(self):
        module = self.module()
        with patch.object(module, 'status_payload', side_effect=RuntimeError('status failed')):
            with self.assertRaises(RuntimeError):
                module.save_chat_configuration(self.payload, self.store)
        self.assertEqual(dict(self.store.values), {'AUTODL_API_KEY': 'unchanged'})


if __name__ == '__main__':
    unittest.main()
