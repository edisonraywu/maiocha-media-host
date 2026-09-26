import base64
import os
import unittest
from unittest.mock import patch

from nacl import public
from automation.core import Blocked, brand_config
from automation.secret_setup import sync_secrets, NAMES


class SecretSetupTests(unittest.TestCase):
    def test_only_verified_baobao_values_are_sealed_and_result_has_no_values(self):
        config = brand_config('baobao')
        config['target'] = {'instagram_user_id': '222', 'facebook_page_id': '333', 'username': 'fixture.baobao'}
        values = dict(config['target'], token='fixture-secret-not-real')
        key = public.PrivateKey.generate()
        stored = {}
        class Meta:
            def verify_account(self):
                return {'username': 'fixture.baobao', 'api_access': True}
        class GitHub:
            def json(self, method, url, **kwargs):
                if url.endswith('/public-key'):
                    return {'key': base64.b64encode(bytes(key.public_key)).decode(), 'key_id': 'fixture'}
                return {'name': url.rsplit('/', 1)[1]}
            def request(self, method, url, body=None, **kwargs):
                self_method = method
                if self_method != 'PUT':
                    raise AssertionError(method)
                plain = public.SealedBox(key).decrypt(base64.b64decode(body['encrypted_value'])).decode()
                stored[url.rsplit('/', 1)[1]] = plain
                return b'', 'application/json'
        env = {config['env'][k]: v for k, v in values.items()} | {'GH_TOKEN': 'fixture-github-token'}
        with patch.dict(os.environ, env):
            result = sync_secrets(config, GitHub(), Meta())
        self.assertEqual(set(stored), NAMES)
        self.assertEqual(stored['BAOBAO_PAGE_ACCESS_TOKEN'], values['token'])
        self.assertNotIn(values['token'], str(result))
        self.assertEqual(result['result'], 'PASS')

    def test_wrong_secret_namespace_stops_before_network(self):
        config = brand_config('baobao')
        config['env']['token'] = 'META_PAGE_ACCESS_TOKEN'
        with self.assertRaisesRegex(Blocked, 'SECRET_DESTINATION_MISMATCH'):
            sync_secrets(config)
