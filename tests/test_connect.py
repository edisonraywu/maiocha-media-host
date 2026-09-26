import os
import unittest
from unittest.mock import patch
import yaml
import test_automation as fixtures
from automation.connect import bind, connect_and_report
from automation.core import Blocked, brand_config, read_json


class ConnectTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown

    def fake(self, missing_permission=False):
        class Api:
            def json(self, method, url, **kwargs):
                if '/oauth/access_token?' in url:
                    return {'access_token': 'fixture-long-user-token'}
                if '/debug_token?' in url:
                    return {'data': {'app_id': '1833218008099793', 'type': 'USER', 'is_valid': True}}
                if '/me/permissions' in url:
                    names = ['pages_show_list', 'pages_read_engagement', 'instagram_basic']
                    if not missing_permission:
                        names.append('instagram_content_publish')
                    return {'data': [{'permission': p, 'status': 'granted'} for p in names]}
                if '/me/accounts?' in url:
                    return {'data': [{'id': '333', 'name': 'fixture page', 'access_token': 'fixture-page-token',
                                      'instagram_business_account': {'id': '222'}}]}
                if '/333?' in url:
                    return {'id': '333', 'name': 'fixture page', 'instagram_business_account': {'id': '222'}}
                if '/content_publishing_limit?' in url:
                    return {'data': [{'config': {'quota_total': 100}, 'quota_usage': 0}]}
                return {'id': '222', 'username': 'fixture.baobao'}
        return Api()

    def configs(self):
        folder = self.repo / 'config/brands'
        folder.mkdir(parents=True)
        for brand in ('baobao', 'maiocha'):
            config = brand_config(brand)
            if brand == 'baobao':
                config['expected_facebook_page_name'] = 'fixture page'
            (folder / (brand + '.yaml')).write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')

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

    def test_wrong_facebook_page_name_cannot_save_credentials(self):
        self.configs()
        path = self.repo / 'config/brands/baobao.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        config['expected_facebook_page_name'] = 'a different page'
        path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_PAGE_NOT_IN_AUTHORIZED_PAGES'):
                bind('fixture.baobao', self.root, self.repo, self.fake())
        self.assertFalse((self.content / '.env').exists())

    def test_second_page_found_without_following_token_bearing_next_url(self):
        self.configs()
        base = self.fake()
        calls = []
        class Api:
            def json(self, method, url, **kwargs):
                calls.append(url)
                if '/me/accounts?' in url and 'after=' not in url:
                    return {'data': [{'id': '444', 'name': 'another page'}], 'paging': {
                        'next': 'https://untrusted.example/PRIVATE_NEXT_URL_TOKEN', 'cursors': {'after': 'fixture-next'}}}
                return base.json(method, url, **kwargs)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            result = connect_and_report('fixture.baobao', self.root, self.repo, Api())
        self.assertEqual(result['instagram_user_id'], '222')
        report = read_json(self.root / '.local/baobao-connect-result.json')
        self.assertEqual(report['page_batches'], 2)
        self.assertEqual(report['authorized_page_count'], 2)
        self.assertNotIn('PRIVATE_NEXT_URL_TOKEN', str(calls) + str(report))
        self.assertNotIn('fixture-page-token', str(report))

    def test_same_page_name_with_wrong_live_ig_username_cannot_bind(self):
        self.configs()
        base = self.fake()
        class Api:
            def json(self, method, url, **kwargs):
                if '/222?' in url:
                    return {'id': '222', 'username': 'wrong.account'}
                return base.json(method, url, **kwargs)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_IG_USERNAME_MISMATCH'):
                connect_and_report('fixture.baobao', self.root, self.repo, Api())
        self.assertFalse((self.content / '.env').exists())

    def test_debug_token_from_another_app_cannot_bind(self):
        self.configs()
        base = self.fake()
        class Api:
            def json(self, method, url, **kwargs):
                if '/debug_token?' in url:
                    return {'data': {'app_id': '999', 'type': 'USER', 'is_valid': True}}
                return base.json(method, url, **kwargs)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'META_APP_ID_MISMATCH'):
                connect_and_report('fixture.baobao', self.root, self.repo, Api())
        self.assertFalse((self.content / '.env').exists())

    def test_empty_page_list_reports_asset_access_without_guessing_ids(self):
        self.configs()
        base = self.fake()
        class Api:
            def json(self, method, url, **kwargs):
                if '/me/accounts?' in url:
                    return {'data': []}
                return base.json(method, url, **kwargs)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_PAGE_NOT_IN_AUTHORIZED_PAGES'):
                connect_and_report('fixture.baobao', self.root, self.repo, Api())
        report = read_json(self.root / '.local/baobao-connect-result.json')
        self.assertEqual(report['authorized_page_count'], 0)
        self.assertEqual(report['missing_permissions'], [])
        self.assertTrue(report['token_valid'])
        self.assertNotIn('fixture-user-token', str(report))
        self.assertFalse((self.content / '.env').exists())

    def test_repeated_page_cursor_stops_instead_of_looping_or_claiming_missing_grant(self):
        self.configs()
        base = self.fake()
        class Api:
            def json(self, method, url, **kwargs):
                if '/me/accounts?' in url:
                    return {'data': [], 'paging': {'next': 'ignored', 'cursors': {'after': 'same'}}}
                return base.json(method, url, **kwargs)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'AUTHORIZED_PAGES_PAGINATION_INVALID'):
                connect_and_report('fixture.baobao', self.root, self.repo, Api())
        self.assertFalse((self.content / '.env').exists())

    def test_failed_connection_records_stage_without_tokens(self):
        self.configs()
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'META_REQUIRED_PERMISSIONS_NOT_GRANTED'):
                connect_and_report('fixture.baobao', self.root, self.repo, self.fake(True))
        report = read_json(self.root / '.local/baobao-connect-result.json')
        self.assertEqual(report['stage'], 'VERIFY_USER_PERMISSIONS')
        self.assertEqual(report['missing_permissions'], ['instagram_content_publish'])
        self.assertEqual(report['error_code'], 'META_REQUIRED_PERMISSIONS_NOT_GRANTED')
        for value in ('fixture-user-token', 'fixture-long-user-token', 'fixture-app-secret', 'fixture-page-token'):
            self.assertNotIn(value, str(report))
        self.assertFalse((self.content / '.env').exists())

    def granted_fallback(self, wrong_page_id=False, wrong_publish_asset=False):
        base = self.fake()
        calls = []
        other_page = brand_config('maiocha')['target']['facebook_page_id']
        class Api:
            def json(self, method, url, **kwargs):
                calls.append(url)
                if '/debug_token?' in url:
                    return {'data': {'app_id': '1833218008099793', 'type': 'USER', 'is_valid': True,
                                     'granular_scopes': [
                                         {'scope': 'pages_show_list', 'target_ids': [other_page, '333']},
                                         {'scope': 'pages_read_engagement', 'target_ids': [other_page, '333']},
                                         {'scope': 'instagram_basic', 'target_ids': ['222']},
                                         {'scope': 'instagram_content_publish', 'target_ids': ['999' if wrong_publish_asset else '222']} ]}}
                if '/me/accounts?' in url:
                    return {'data': []}
                if '/333?' in url and 'access_token' in url:
                    return {'id': '999' if wrong_page_id else '333', 'name': 'fixture page',
                            'access_token': 'fixture-page-token', 'instagram_business_account': {'id': '222'}}
                return base.json(method, url, **kwargs)
        return Api(), calls, other_page

    def test_granted_page_can_bind_when_me_accounts_is_empty(self):
        self.configs()
        api, calls, other_page = self.granted_fallback()
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            result = connect_and_report('fixture.baobao', self.root, self.repo, api)
        self.assertEqual(result['facebook_page_id'], '333')
        self.assertFalse(any('/' + other_page + '?' in url for url in calls))
        report = read_json(self.root / '.local/baobao-connect-result.json')
        self.assertEqual(report['discovery_method'], 'EXPLICIT_TOKEN_ASSET_GRANTS')
        self.assertEqual(report['authorized_page_count'], 0)
        self.assertTrue(report['direct_granted_page_lookups'][0]['page_token_available'])
        self.assertNotIn('fixture-page-token', str(report))

    def test_direct_lookup_must_return_the_granted_page_id(self):
        self.configs()
        api, _, _ = self.granted_fallback(wrong_page_id=True)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'GRANTED_PAGE_ID_MISMATCH'):
                connect_and_report('fixture.baobao', self.root, self.repo, api)
        self.assertFalse((self.content / '.env').exists())

    def test_global_publish_permission_for_another_ig_cannot_bind(self):
        self.configs()
        api, _, _ = self.granted_fallback(wrong_publish_asset=True)
        with patch.dict(os.environ, {'BAOBAO_SETUP_USER_TOKEN': 'fixture-user-token', 'BAOBAO_SETUP_APP_SECRET': 'fixture-app-secret'}):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_ASSET_PERMISSION_MISMATCH'):
                connect_and_report('fixture.baobao', self.root, self.repo, api)
        self.assertFalse((self.content / '.env').exists())
