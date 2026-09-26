"""Review preparation can never stand in for the owner's explicit approval."""
import copy
import unittest
from unittest.mock import patch

import test_automation as fixtures
from automation.core import Blocked, digest, file_hash, item_dir, read_json
from automation.cli import parser, run
from automation.journal import claim, schedule_release
from automation.pipeline import check_prepared, revise_one
from automation.preview import render_preview
from automation.publisher import preview_preflight
from automation.release import build_release, validate_release


class ReviewGateTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown
    product = fixtures.PipelineTests.product
    prepared = fixtures.PipelineTests.prepared
    release = fixtures.PipelineTests.release
    publisher = fixtures.PipelineTests.publisher

    def test_prepare_cli_stops_at_review_and_never_creates_approval_or_queue(self):
        self.product()
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'prepare'])
        with patch('automation.cli.brand_config', return_value=self.config), \
             patch('automation.cli.CodexBatchGenerator', return_value=fixtures.FixtureGenerator()), \
             patch('automation.publisher.MetaClient', return_value=fixtures.FakeMeta()), \
             patch('automation.cli.GitHubJournal', side_effect=AssertionError('Must not create remote queue')):
            result = run(args)
        self.assertEqual(result['items'][0]['status'], 'READY_FOR_REVIEW')
        self.assertFalse(result['approval_granted'])
        self.assertIsNone(result['scheduling'])
        item = read_json(item_dir(self.content, result['items'][0]['content_id']) / 'item.json')
        self.assertIsNone(item['approval'])
        calendar = read_json(self.content / 'calendar/calendar.json')
        self.assertEqual(calendar['items'][0]['schedule_state'], 'PROPOSED_SCHEDULE')

    def test_unapproved_statuses_block_direct_test_and_normal_publish_before_network(self):
        _, approved = self.release()
        for status in ('DRAFT', 'PREPARED', 'READY', 'READY_FOR_REVIEW', 'NEEDS_INFO'):
            for test_only in (False, True):
                pack = copy.deepcopy(approved)
                pack['status'] = status
                meta = fixtures.FakeMeta()
                with self.subTest(status=status, test=test_only), self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
                    self.publisher(meta).publish(pack, test_only=test_only)
                self.assertEqual(meta.posts, [])
                self.assertEqual(meta.verifications, 0)
        self.assertEqual(self.state.state['items'], {})

    def test_auto_flag_cannot_bypass_manual_release_approval(self):
        _, pack = self.release()
        self.config['approval_mode'] = False
        self.config['auto_publish_without_approval'] = True
        pack['approval']['mode'] = 'auto'
        with self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
            self.publisher().publish(pack)

    def test_missing_approval_blocks_direct_schedule_and_claim(self):
        _, pack = self.release()
        pack['approval'] = None
        for entry in (schedule_release, claim):
            with self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
                entry(self.state, pack)
        self.assertEqual(self.state.state['queue'], {})
        self.assertEqual(self.state.state['items'], {})

    def test_modified_release_cannot_reuse_approval_even_if_release_hash_rebuilt(self):
        _, pack = self.release()
        pack['publish_at'] = '2027-01-01T20:00:00+08:00'
        pack['release_hash'] = digest({k: v for k, v in pack.items() if k != 'release_hash'})
        with self.assertRaisesRegex(Blocked, 'APPROVAL_MISSING_OR_STALE'):
            validate_release(self.repo, pack, self.config)

    def test_preview_contains_three_candidates_order_source_and_expected_account(self):
        item = self.prepared(count=2)
        page = render_preview(self.content, self.config).read_text(encoding='utf-8')
        self.assertTrue(all('文案 ' + key in page for key in 'ABC'))
        self.assertIn(item['source_folder'], page)
        self.assertIn(self.config['target']['username'], page)
        self.assertIn('READY_FOR_REVIEW', page)
        self.assertIn('封面', page)
        saved = read_json(item_dir(self.content, item['content_id']) / 'item.json')
        self.assertIsNone(saved['approval'])

    def test_preview_preflight_does_not_approve_or_publish_or_claim_hosting_pass(self):
        item = self.prepared()
        meta = fixtures.FakeMeta()
        report = preview_preflight(self.repo, self.content, item, self.config, meta)
        self.assertEqual(report['stage'], 'PREVIEW_PREFLIGHT')
        self.assertEqual(report['checks']['hosting'], 'PENDING_EXPLICIT_APPROVAL')
        self.assertEqual(report['api_post_requests_sent'], 0)
        self.assertIsNone(item['approval'])
        self.assertEqual(meta.posts, [])

    def test_revise_touches_only_requested_caption_and_reuses_grounding(self):
        one = self.prepared(name='one')
        two = self.prepared(name='two')
        folder = item_dir(self.content, one['content_id'])
        other = item_dir(self.content, two['content_id']) / 'item.json'
        prior, grounding = file_hash(other), file_hash(folder / 'product_grounding.json')
        generator = fixtures.FixtureGenerator()
        result = revise_one(self.content, one, self.config, generator, instructions='短一點，不要夢幻')
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        self.assertEqual(file_hash(other), prior)
        self.assertEqual(file_hash(folder / 'product_grounding.json'), grounding)
        self.assertTrue(all(stage in ('captions', 'qa', 'style_qa') and cid == one['content_id'] for stage, cid, _ in generator.calls))
        self.assertIsNone(result['approval'])

    def test_reorder_keeps_caption_and_requires_fresh_review(self):
        item, _ = self.release(count=2)
        folder = item_dir(self.content, item['content_id'])
        caption = file_hash(folder / 'selected_caption.txt')
        generator = fixtures.FixtureGenerator()
        order = list(reversed(item['selected_photo_ids']))
        result = revise_one(self.content, item, self.config, generator, photo_ids=order)
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        self.assertEqual(result['selected_photo_ids'], order)
        self.assertEqual(file_hash(folder / 'selected_caption.txt'), caption)
        self.assertEqual([stage for stage, _, _ in generator.calls], ['qa', 'style_qa'])
        self.assertEqual(check_prepared(self.content, result)['result'], 'PASS')
        with self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
            build_release(self.content, result, self.config)

    def test_mode_auto_is_rejected(self):
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'mode', 'auto'])
        with patch('automation.cli.brand_config', return_value=self.config), self.assertRaisesRegex(Blocked, 'AUTO_PUBLISH_DISABLED'):
            run(args)

    def test_actions_validation_reads_pause_and_only_secret_presence(self):
        self.state.state['paused'] = True
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'validate'])
        with patch('automation.cli.brand_config', return_value=self.config), patch('automation.cli.GitHubJournal', return_value=self.state):
            report = run(args)
        self.assertTrue(report['paused'])
        self.assertEqual(report['api_post_requests_sent'], 0)
        self.assertNotIn('fixture-not-a-real-token', str(report))
        self.assertTrue(all(value is True for value in report['secret_presence'].values()))

    def test_live_account_validation_is_read_only_and_keeps_pause(self):
        self.state.state['paused'] = True
        meta = fixtures.FakeMeta()
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'validate', '--live-account'])
        with patch('automation.cli.brand_config', return_value=self.config), \
             patch('automation.cli.GitHubJournal', return_value=self.state), patch('automation.cli.MetaClient', return_value=meta):
            report = run(args)
        self.assertEqual(report['account_safety_gate'], 'PASS')
        self.assertEqual(meta.verifications, 1)
        self.assertEqual(meta.posts, [])
        self.assertTrue(self.state.state['paused'])
        self.assertEqual(report['namespaces']['assets'], 'media/baobao')
        self.assertNotIn('fixture-not-a-real-token', str(report))

    def test_live_account_validation_rejects_wrong_real_account(self):
        meta = fixtures.FakeMeta(wrong=True)
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'validate', '--live-account'])
        with patch('automation.cli.brand_config', return_value=self.config), \
             patch('automation.cli.GitHubJournal', return_value=self.state), patch('automation.cli.MetaClient', return_value=meta):
            with self.assertRaisesRegex(Blocked, 'LIVE_ACCOUNT_MISMATCH'):
                run(args)
        self.assertEqual(meta.posts, [])
