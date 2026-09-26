import base64
import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from automation.core import Blocked, brand_config, digest
from automation.journal import GitHubJournal, initial_state, schedule_release, revoke_scheduled
from automation.network import ApiFailure, Transport, MetaClient
import test_automation as fixtures
from test_automation import FakeMeta


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        from email.message import Message
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'


class Opener:
    def __init__(self, failures=0):
        self.failures, self.calls = failures, []

    def open(self, request, timeout):
        self.calls.append(request)
        if len(self.calls) <= self.failures:
            raise urllib.error.URLError('SIMULATED_PRIVATE_ERROR_TEXT')
        return Response(b'{"ok": true}')


class NetworkTests(unittest.TestCase):
    def test_http_failure_retains_only_numeric_provider_diagnostics(self):
        net = Transport(sleep=lambda _: None)
        body = json.dumps({'error': {'code': 190, 'error_subcode': 463,
                                    'message': 'SIMULATED_PRIVATE_TOKEN_AND_URL'}}).encode()
        error = urllib.error.HTTPError('https://graph.facebook.com/private', 400, 'private', {}, io.BytesIO(body))
        with patch.object(net.opener, 'open', side_effect=error):
            with self.assertRaises(ApiFailure) as raised:
                net.json('GET', 'https://graph.facebook.com/v26.0/me')
        failure = raised.exception
        self.assertEqual((failure.provider_code, failure.provider_subcode), (190, 463))
        self.assertEqual(str(failure), 'HTTP_400')
        self.assertNotIn('SIMULATED_PRIVATE', str(vars(failure)))

    def test_get_bounded_retry_and_no_sensitive_error_text(self):
        net = Transport(sleep=lambda _: None)
        net.opener = Opener(failures=10)
        with self.assertRaisesRegex(ApiFailure, '^NETWORK_UNAVAILABLE$'):
            net.json('GET', 'https://graph.facebook.com/v26.0/me')
        self.assertEqual(len(net.opener.calls), 3)

    def test_post_no_automatic_retry_even_on_network_failure(self):
        net = Transport(sleep=lambda _: None)
        net.opener = Opener(failures=10)
        with self.assertRaises(ApiFailure):
            net.json('POST', 'https://graph.facebook.com/v26.0/222/media_publish', body={'creation_id': '1'})
        self.assertEqual(len(net.opener.calls), 1)

    def test_chinese_caption_roundtrips_through_real_form_encoder(self):
        from urllib.parse import parse_qs
        net = Transport(sleep=lambda _: None)
        net.opener = Opener()
        text = '寶寶，你的礦到了。\n這一串的藍與白。'
        net.json('POST', 'https://graph.facebook.com/v26.0/222/media', body={'caption': text}, form=True)
        req = net.opener.calls[0]
        self.assertEqual(parse_qs(req.data.decode())['caption'], [text])

    def test_meta_account_checks_real_page_and_username_logic(self):
        class Responses:
            def json(self, method, url, **kwargs):
                if '/333?' in url:
                    return {'id': '333', 'instagram_business_account': {'id': 'WRONG'}}
                return {'id': '222', 'username': 'fixture.baobao'}
        config = brand_config('baobao')
        config['target'] = {'facebook_page_id': '333', 'instagram_user_id': '222', 'username': 'fixture.baobao'}
        meta = MetaClient(config, dict(config['target'], token='fixture'), Responses())
        with self.assertRaisesRegex(Blocked, 'LIVE_ACCOUNT_MISMATCH'):
            meta.verify_account()


class GitHubApi:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.sha = 'initial'
        self.lost_put = False
        self.conflict = False
        self.calls = []

    def json(self, method, url, headers=None, body=None):
        self.calls.append((method, url))
        if method == 'GET':
            return {'sha': self.sha, 'content': base64.b64encode(json.dumps(self.state).encode()).decode()}
        if method == 'PUT':
            if self.conflict or body.get('sha') != self.sha:
                raise ApiFailure('HTTP_409', 409)
            self.state = json.loads(base64.b64decode(body['content']))
            self.sha = digest(self.state)
            if self.lost_put:
                raise ApiFailure('NETWORK_UNAVAILABLE', transient=True)
            return {'content': {'sha': self.sha}}
        raise AssertionError(method)


class JournalTests(unittest.TestCase):
    def test_successful_put_with_lost_response_is_reconciled_without_retry(self):
        api = GitHubApi(initial_state('baobao'))
        api.lost_put = True
        journal = GitHubJournal(brand_config('baobao'), token='fixture', transport=api)
        journal.mutate(lambda s: s.update(paused=False))
        self.assertFalse(api.state['paused'])
        self.assertEqual(sum(method == 'PUT' for method, _ in api.calls), 1)

    def test_cas_conflict_stops_instead_of_overwriting_other_runner(self):
        api = GitHubApi(initial_state('baobao'))
        api.conflict = True
        journal = GitHubJournal(brand_config('baobao'), token='fixture', transport=api)
        with self.assertRaisesRegex(Blocked, 'JOURNAL_CONCURRENT_CHANGE'):
            journal.mutate(lambda s: s.update(paused=False))

    def test_wrong_brand_history_is_never_accepted(self):
        journal = GitHubJournal(brand_config('baobao'), token='fixture', transport=GitHubApi(initial_state('maiocha')))
        with self.assertRaisesRegex(Blocked, 'JOURNAL_BRAND'):
            journal.read()


class SchedulingRaceTests(fixtures.PipelineTests):
    # Reuse fixture setup/helpers but avoid inheriting all tests a second time in discovery.
    def test_schedule_revocation_blocks_previously_loaded_release(self):
        _, pack = self.release()
        schedule_release(self.state, pack)
        revoke_scheduled(self.state, pack['content_id'])
        from automation.journal import claim
        with self.assertRaisesRegex(Blocked, 'SCHEDULE_REVOKED'):
            claim(self.state, pack, due=True)

    def test_stale_scheduler_package_cannot_use_new_approval(self):
        _, pack = self.release()
        replacement = copy.deepcopy(pack)
        replacement['release_hash'] = 'new-version'
        schedule_release(self.state, replacement)
        report = self.publisher(FakeMeta()).publish(pack, dry_run=True)
        self.assertNotEqual(report['result'], 'PASS')

    def test_schedule_runs_hosting_preflight_then_persists_exact_queue(self):
        from automation.operations import schedule_batch
        from test_automation import HostedFiles
        item, pack = self.release()
        hosted = []
        reports = schedule_batch(self.repo, self.root, self.content, self.config, [item], self.state,
            meta=FakeMeta(), transport=HostedFiles(self.repo, self.config), host_action=lambda: hosted.append(True))
        self.assertEqual(hosted, [True])
        self.assertEqual(reports[0]['result'], 'PASS')
        self.assertEqual(self.state.state['queue'][item['content_id']]['release_hash'], pack['release_hash'])
        self.assertEqual(fixtures.read_json(fixtures.item_dir(self.content, item['content_id']) / 'item.json')['status'], 'SCHEDULED')

    def test_first_test_schedule_does_not_authorize_cron_publishing(self):
        from automation.operations import schedule_batch
        from test_automation import HostedFiles
        item, pack = self.release()
        self.state.state['production_ready'] = False
        reports = schedule_batch(self.repo, self.root, self.content, self.config, [item], self.state,
            test_only=True, meta=FakeMeta(), transport=HostedFiles(self.repo, self.config), host_action=lambda: None)
        self.assertEqual(reports[0]['result'], 'PASS')
        self.assertEqual(self.state.state['queue'], {})

    def test_auto_mode_cannot_schedule_without_explicit_approval(self):
        from automation.operations import schedule_batch
        from test_automation import HostedFiles
        from datetime import datetime, timezone, timedelta
        self.config['approval_mode'] = False
        item = self.prepared()
        item['publish_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
            schedule_batch(self.repo, self.root, self.content, self.config, [item], self.state,
                meta=FakeMeta(), transport=HostedFiles(self.repo, self.config), host_action=lambda: self.fail('Must not host'))
        self.assertEqual(self.state.state['queue'], {})


# unittest normally inherits base test methods; keep this class limited to its two added cases.
for _name in dir(fixtures.PipelineTests):
    if _name.startswith('test_') and _name not in SchedulingRaceTests.__dict__:
        setattr(SchedulingRaceTests, _name, None)
