"""Adversarial brand-boundary tests. Synthetic local data and mocked APIs only."""
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

import test_automation as fixtures
from test_network_journal import GitHubApi
from automation.core import Blocked, brand_config, item_dir, read_json
from automation.hosting_scope import canonical_key, public_asset_key, scoped_key
from automation.journal import GitHubJournal, LocalTestJournal, claim, initial_state, schedule_release
from automation.operations import host
from automation.pipeline import observe_product, prepare_one
from automation.release import approve, stage_release, validate_release
from automation.style import load_profile, require_formal_item


class BoundaryTests(unittest.TestCase):
    def test_cross_brand_prefix_and_encoded_traversal_rejected(self):
        namespace = 'media/baobao/baobao-BB001'
        for key in (
            'media/maiocha/x.jpg', 'media/baobao-malicious/baobao-BB001/x.jpg',
            namespace + '-other/x.jpg', namespace + '/../../maiocha/x.jpg',
            namespace + '/%2e%2e/%2e%2e/maiocha/x.jpg',
            namespace + '/%252e%252e/%252e%252e/maiocha/x.jpg',
            namespace + r'\..\..\maiocha\x.jpg', namespace + './x.jpg', namespace + '/x.jpg:stream',
        ):
            with self.subTest(key=key), self.assertRaises(Blocked):
                scoped_key(key, namespace)

    def test_normalization_keeps_only_true_path_segment_descendants(self):
        self.assertEqual(canonical_key('media//baobao/./baobao-BB001/feed/../01.jpg'), 'media/baobao/baobao-BB001/01.jpg')
        self.assertEqual(scoped_key('media/maiocha-campaign/a.jpg', 'media/maiocha-campaign'), 'media/maiocha-campaign/a.jpg')
        with self.assertRaises(Blocked):
            scoped_key('media/maiocha-campaign-other/a.jpg', 'media/maiocha-campaign')

    def test_exact_release_url_and_namespace_are_bound(self):
        config = brand_config('baobao')
        cid = 'baobao-BB001'
        key = f'media/baobao/{cid}/01.jpg'
        good = config['hosting']['base_url'] + '/' + key
        self.assertEqual(public_asset_key(config, cid, key, good), key)
        for url in (good + '?other=1', good + '#other', good.replace('/media/baobao/', '/media/maiocha/')):
            with self.assertRaises(Blocked):
                public_asset_key(config, cid, key, url)
        with self.assertRaises(Blocked):
            public_asset_key(config, cid, f'media/baobao/{cid}/%2e/01.jpg')


class StateIsolationTests(unittest.TestCase):
    def test_baobao_pause_does_not_change_maiocha(self):
        self._pause_isolated('baobao', 'maiocha')

    def test_maiocha_pause_does_not_change_baobao(self):
        self._pause_isolated('maiocha', 'baobao')

    def _pause_isolated(self, changed, other):
        states = {b: initial_state(b) for b in (changed, other)}
        for state in states.values():
            state['paused'] = False
        apis = {b: GitHubApi(s) for b, s in states.items()}
        journals = {b: GitHubJournal(brand_config(b), token='fixture-only', transport=apis[b]) for b in states}
        journals[changed].mutate(lambda s: s.update(paused=True))
        self.assertTrue(apis[changed].state['paused'])
        self.assertFalse(apis[other].state['paused'])
        self.assertFalse(apis[other].calls)
        self.assertTrue(all('/state/' + changed + '.json' in url for _, url in apis[changed].calls))

    def test_foreign_history_is_rejected_before_duplicate_detection(self):
        state = initial_state('baobao')
        state['history'] = [{'brand': 'maiocha', 'content_id': 'maiocha-product', 'status': 'PUBLISHED', 'source_asset_hashes': ['same-hash']}]
        journal = GitHubJournal(brand_config('baobao'), token='fixture', transport=GitHubApi(state))
        with self.assertRaisesRegex(Blocked, 'JOURNAL_CROSS_BRAND_RECORD'):
            journal.read()

    def test_journal_write_cannot_replace_brand(self):
        api = GitHubApi(initial_state('baobao'))
        journal = GitHubJournal(brand_config('baobao'), token='fixture', transport=api)
        with self.assertRaisesRegex(Blocked, 'JOURNAL_BRAND'):
            journal.write(initial_state('maiocha'), 'initial')
        self.assertFalse(api.calls)

    def test_workflow_has_only_baobao_meta_secrets_and_scoped_concurrency(self):
        from automation.core import REPO
        source = (REPO / '.github/workflows/baobao-publish.yml').read_text(encoding='utf-8')
        for name in ('BAOBAO_IG_USER_ID','BAOBAO_PAGE_ID','BAOBAO_IG_USERNAME','BAOBAO_PAGE_ACCESS_TOKEN'):
            self.assertIn('secrets.' + name, source)
        self.assertNotIn('secrets.META_PAGE_ACCESS_TOKEN', source)
        self.assertIn('group: instagram-baobao', source)


class ContentIsolationTests(fixtures.PipelineTests):
    def test_wrong_config_cannot_reach_grounding_or_caption_generator(self):
        item = self.prepared()
        wrong = brand_config('maiocha')
        gen = fixtures.FixtureGenerator()
        before = (item_dir(self.content, item['content_id']) / 'item.json').read_bytes()
        for action in (lambda: observe_product(self.content, item, wrong, gen),
                       lambda: prepare_one(self.content, item, wrong, gen, [])):
            with self.assertRaisesRegex(Blocked, 'ITEM_BRAND_CONTEXT_MISMATCH'):
                action()
        self.assertFalse(gen.calls)
        self.assertEqual(before, (item_dir(self.content, item['content_id']) / 'item.json').read_bytes())

    def test_baobao_approval_cannot_approve_maiocha_item(self):
        foreign = {'brand': 'maiocha', 'content_id': 'maiocha-product', 'status': 'READY_FOR_REVIEW'}
        with self.assertRaisesRegex(Blocked, 'ITEM_BRAND_CONTEXT_MISMATCH'):
            approve(self.content, foreign, self.config)
        self.assertNotIn('approval', foreign)

    def test_maiocha_approval_cannot_approve_baobao_item(self):
        item = self.prepared()
        with self.assertRaisesRegex(Blocked, 'ITEM_BRAND_CONTEXT_MISMATCH'):
            approve(self.content, item, brand_config('maiocha'))
        self.assertEqual(read_json(item_dir(self.content, item['content_id']) / 'item.json')['approval_state'], 'PENDING')

    def test_baobao_style_profile_cannot_be_loaded_for_maiocha(self):
        other = self.content.parent / 'maiocha'
        with patch('automation.style.read_yaml', side_effect=AssertionError('must reject before reading')):
            with self.assertRaisesRegex(Blocked, 'BAOBAO_STYLE_PROFILE_CONTEXT_REQUIRED'):
                load_profile(other)
            with self.assertRaisesRegex(Blocked, 'BAOBAO_STYLE_PROFILE_CONTEXT_REQUIRED'):
                require_formal_item(self.content, {'brand':'maiocha','content_id':'maiocha-product'})

    def test_release_cannot_enter_other_brand_queue_or_claim(self):
        _, pack = self.release()
        foreign = LocalTestJournal('maiocha')
        foreign.state.update(paused=False, production_ready=True)
        for action in (lambda: schedule_release(foreign, pack), lambda: claim(foreign, pack)):
            with self.assertRaisesRegex(Blocked, 'JOURNAL_RELEASE_BRAND_MISMATCH'):
                action()
        self.assertFalse(foreign.state['items'])
        self.assertFalse(foreign.state['queue'])

    def test_cross_brand_staging_is_rejected_before_writing(self):
        item, _ = self.release()
        wrong = copy.deepcopy(self.config)
        wrong['hosting']['namespace'] = 'media/maiocha'
        with self.assertRaisesRegex(Blocked, 'HOSTING_BRAND_CONTEXT_MISMATCH'):
            stage_release(self.repo, self.content, item, wrong)
        self.assertFalse((self.repo / 'media/maiocha').exists())

    def test_host_rejects_other_brand_staged_files_before_git_mutations(self):
        commands = []
        def git_run(args, **kwargs):
            commands.append(args)
            tail = args[3:]
            output = (b'https://github.com/edisonraywu/maiocha-media-host.git' if tail[:2] == ['remote','get-url'] else
                      b'main' if tail[:2] == ['branch','--show-current'] else b'media/maiocha-old/01.jpg')
            return subprocess.CompletedProcess(args, 0, output, b'')
        with patch('automation.operations.subprocess.run', side_effect=git_run):
            with self.assertRaisesRegex(Blocked, 'UNRELATED_STAGED_FILES'):
                host(self.repo, self.root, self.config)
        self.assertFalse(any(args[3] in ('add','commit','push','fetch') for args in commands))


for _name in dir(fixtures.PipelineTests):
    if _name.startswith('test_') and _name not in ContentIsolationTests.__dict__:
        setattr(ContentIsolationTests, _name, None)
