import os
import unittest
from unittest.mock import patch
import yaml
import test_automation as fixtures
from automation.connect import bind
from automation.core import Blocked, brand_config


class ConnectTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown

    def fake(self, missing_permission=False):
        class Api:
            def json(self, method, url, **kwargs):
                if '/oauth/access_token?' in url:
                    return {'access_token': 'fixture-long-user-token'}
                if '/me/permissions' in url:
                    names = ['pages_show_list', 'pages_read_engagement', 'instagram_basic']
                    if not missing_permission:
                        names.append('instagram_content_publish')
                    return {'data': [{'permission': p, 'status': 'granted'} for p in names]}
                if '/me/accounts?' in url:
                    return {'data': [{'id': '333', 'name': 'fixture page', 'access_token': 'fixture-page-token',
                                      'instagram_business_account': {'id': '222', 'username': 'fixture.baobao'}}]}
                if '/333?' in url:
                    return {'id': '333', 'instagram_business_account': {'id': '222'}}
                if '/content_publishing_limit?' in url:
                    return {'data': [{'config': {'quota_total': 100}, 'quota_usage': 0}]}
                return {'id': '222', 'username': 'fixture.baobao'}
        return Api()

    def configs(self):
        folder = self.repo / 'config/brands'
        folder.mkdir(parents=True)
        for brand in ('baobao', 'maiocha'):
            (folder / (brand + '.yaml')).write_text(yaml.safe_dump(brand_config(brand), allow_unicode=True), encoding='utf-8')

    def test_bind_uses_existing_app_and_only_saves_verified_account(self):
        self.configs()
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            verified = bind('fixture.baobao', self.root, self.repo, self.fake())
        self.assertEqual(verified['username'], 'fixture.baobao')
        self.assertIn('instagram_content_publish', verified['granted_permissions'])
        self.assertIn('BAOBAO_PAGE_ACCESS_TOKEN=fixture-page-token', (self.content / '.env').read_text())
        self.assertNotIn('fixture-page-token', (self.repo / 'config/brands/baobao.yaml').read_text(encoding='utf-8'))
        self.assertNotIn('fixture-page-token', str(verified))

    def test_missing_publish_permission_cannot_save_credentials(self):
        self.configs()
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'META_REQUIRED_PERMISSIONS_NOT_GRANTED'):
                bind('fixture.baobao', self.root, self.repo, self.fake(True))
        self.assertFalse((self.content / '.env').exists())

    def test_maiocha_username_cannot_be_bound_to_baobao(self):
        self.configs()
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token'}):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_USERNAME_REQUIRED'):
                bind('maiocha.lab', self.root, self.repo, self.fake())
