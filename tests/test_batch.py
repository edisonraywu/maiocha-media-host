"""Engineering fixtures only. These tests do not certify real merchandise/captions."""
import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from PIL import Image, ImageDraw

import test_automation as fixtures
from automation.batch import (add_photos, approve_range, assert_batch_binding, intake_batch, parse_intake,
                              prepare_batch, refresh_batch, resolve_item, update_product)
from automation.calendar import plan_calendar
from automation.cli import parser, run
from automation.core import Blocked, file_hash, item_dir, read_json, save_json
from automation.pipeline import check_prepared, revise_one
from automation.preview import render_preview
from automation.qa import caption_errors
from automation.release import approve, build_release, stage_release


class BatchTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown
    publisher = fixtures.PipelineTests.publisher

    def intake(self, count=1, *, text=None, duplicate=False):
        self.config['posting']['default_publish_time'] = '10:00'
        source = self.root / 'attachments'
        source.mkdir(exist_ok=True)
        lines = ['Batch：2026-10-01～2026-10-14']
        for n in range(count):
            ref = f'BB{n + 1:03d}'
            folder = source / ref
            folder.mkdir(exist_ok=True)
            for i in range(6):
                image = Image.new('RGB', (640, 800), (60 + n * 3, 120 + i * 5, 170))
                ImageDraw.Draw(image).text((20, 20), f'FIXTURE {ref} angle {i}', fill='white')
                image.save(folder / f'IMG_{i + 1:03d}.jpg')
            lines.append(f'{ref} 海藍寶 10/{n + 1}')
        if duplicate:
            (source / 'BB001' / 'DUPLICATE.jpg').write_bytes((source / 'BB001' / 'IMG_001.jpg').read_bytes())
        return intake_batch(self.content, self.config, text or '\n'.join(lines), source, year=2026)

    def prepared(self, count=1, **kwargs):
        manifest = self.intake(count, **kwargs)
        generator = fixtures.FixtureGenerator()
        items = prepare_batch(self.content, self.config, manifest['batch_id'], lambda: generator)
        return manifest, items, generator

    def assert_batch_size(self, count):
        manifest, items, gen = self.prepared(count)
        self.assertEqual(len(items), count)
        all_hashes = set()
        for n, item in enumerate(items):
            self.assertEqual(item['status'], 'READY_FOR_REVIEW', item.get('prepare_errors'))
            self.assertEqual(len(item['photos']), 6)
            self.assertEqual(len(item['selected_photo_ids']), 6)
            self.assertEqual(item['content_type'], 'CAROUSEL')
            self.assertEqual(item['publish_at'], f'2026-10-{n + 1:02d}T10:00:00+08:00')
            self.assertEqual(item['approval_state'], 'PENDING')
            self.assertIsNone(item['approval'])
            folder = item_dir(self.content, item['content_id'])
            for file in ('product_grounding.json', 'caption_basis.json', 'caption_candidates.json', 'caption_qa.json'):
                self.assertEqual(read_json(folder / file)['content_id'], item['content_id'])
            for asset in item['photos']:
                self.assertEqual(asset['content_id'], item['content_id'])
                self.assertTrue(asset['asset_id'].startswith(item['content_id']))
                self.assertNotIn(asset['source_sha256'], all_hashes)
                all_hashes.add(asset['source_sha256'])
            self.assertEqual(check_prepared(self.content, item)['result'], 'PASS')
        self.assertEqual(len(all_hashes), 6 * count)
        before = len(gen.calls)
        prepare_batch(self.content, self.config, manifest['batch_id'], lambda: gen)
        self.assertEqual(len(gen.calls), before, 'unchanged batch must reuse prior work')
        plan_calendar(self.content, self.config, datetime(2026, 10, 1, tzinfo=timezone.utc))
        for old in items:
            self.assertEqual(read_json(item_dir(self.content, old['content_id']) / 'item.json')['publish_at'], old['publish_at'])
        page = render_preview(self.content, self.config)
        preview = read_json(page.with_suffix('.json'))
        self.assertEqual(len(preview['items']), count)
        for row in preview['items']:
            self.assertEqual(len(row['photo_plan']), 6)
            self.assertEqual(len(row['caption_candidates']), 3)
            self.assertTrue(all(p['reason'] for p in row['photo_plan']))
        self.assertFalse((self.repo / 'releases').exists())

    def test_seven_products_six_photos_binding_dates_preview_and_idempotency(self):
        self.assert_batch_size(7)

    def test_fourteen_products_six_photos_binding_dates_preview_and_idempotency(self):
        self.assert_batch_size(14)

    def test_natural_language_multiline_optional_facts_and_time_override(self):
        self.config['posting']['default_publish_time'] = '20:00'
        result = parse_intake('這批排 10/1～10/14。\nBB001：\n海藍寶\n10/1 19:30\n[6張照片]\n價格: 3,280\n珠徑: 10mm\nSKU: X001\n庫存: 1\n備註: 我提供的備註\n10/2 BB002 綠碧璽', self.config, year=2026)
        one, two = result['products']
        self.assertEqual(one['crystal_name'], '海藍寶')
        self.assertEqual(one['price'], 3280)
        self.assertEqual(one['sku'], 'X001')
        self.assertEqual(one['bead_size'], '10mm')
        self.assertEqual(one['publish_at'], '2026-10-01T19:30:00+08:00')
        self.assertEqual(two['publish_time'], '20:00')
        self.assertEqual(two['crystal_name'], '綠碧璽')
        self.assertEqual(one['issues'], [])

    def test_missing_crystal_identity_grounding_only_never_guessed(self):
        _, items, gen = self.prepared(text='Batch 2026-10-01～2026-10-14\nBB001 10/1')
        item = items[0]
        self.assertEqual(item['status'], 'NEEDS_INFO')
        self.assertIn('USER_CRYSTAL_NAME_REQUIRED', item['prepare_errors'])
        self.assertEqual([s for s, _, _ in gen.calls], ['grounding'])
        grounding = read_json(item_dir(self.content, item['content_id']) / 'product_grounding.json')
        self.assertIsNone(grounding['user_provided']['crystal_name'])

    def test_crystal_name_cannot_be_inferred_from_product_name(self):
        _, items, _ = self.prepared(text='Batch 2026-10-01～2026-10-14\nBB001 10/1\n商品名稱: 海藍寶手串')
        self.assertEqual(items[0]['status'], 'NEEDS_INFO')
        self.assertIsNone(items[0]['user_provided']['crystal_name'])

    def test_exact_duplicate_retained_and_visible_as_exclusion(self):
        _, items, _ = self.prepared(duplicate=True)
        item = items[0]
        self.assertEqual(len(item['photos']), 6)
        self.assertEqual(len(item['duplicates_removed']), 1)
        duplicate = item['duplicates_removed'][0]
        self.assertTrue((item_dir(self.content, item['content_id']) / duplicate['original_path']).exists())
        page = render_preview(self.content, self.config).read_text(encoding='utf-8')
        self.assertIn('RECOMMEND_EXCLUDE', page)
        self.assertIn('DUPLICATE.jpg', page)

    def test_cross_product_identical_hash_blocks_both_products(self):
        manifest = self.intake(2)
        # Simulate an owner input that accidentally attached one photo to two groups.
        source = self.root / 'attachments'
        (source / 'BB002/IMG_001.jpg').write_bytes((source / 'BB001/IMG_001.jpg').read_bytes())
        other_content = self.root / 'separate/content/baobao'
        other_content.mkdir(parents=True)
        text = (self.content / 'batches' / manifest['batch_id'] / 'intake.txt').read_text(encoding='utf-8')
        new = intake_batch(other_content, self.config, text, source, year=2026)
        gen = fixtures.FixtureGenerator()
        items = prepare_batch(other_content, self.config, new['batch_id'], lambda: gen)
        self.assertEqual([x['status'] for x in items], ['NEEDS_INFO', 'NEEDS_INFO'])
        self.assertTrue(all('CROSS_PRODUCT_PHOTO_HASH' in x['prepare_errors'] for x in items))
        self.assertEqual(gen.calls, [])

    def test_user_dates_preserved_even_on_collision(self):
        manifest, items, _ = self.prepared(2, text='Batch 2026-10-01～2026-10-14\nBB001 海藍寶 10/1\nBB002 海藍寶 10/1 21:00')
        batch = refresh_batch(self.content, manifest['batch_id'])
        self.assertIn('2026-10-01', batch['conflicts']['dates'])
        self.assertTrue(all(x['schedule_warnings'] == ['SAME_DAY_MULTIPLE_PRODUCTS'] for x in batch['products']))
        before = [x['publish_at'] for x in items]
        plan_calendar(self.content, self.config)
        self.assertEqual([read_json(item_dir(self.content, x['content_id']) / 'item.json')['publish_at'] for x in items], before)

    def test_missing_date_does_not_acquire_automatic_calendar_slot(self):
        _, items, _ = self.prepared(text='BB001 海藍寶')
        self.assertEqual(items[0]['status'], 'NEEDS_INFO')
        plan_calendar(self.content, self.config)
        self.assertIsNone(read_json(item_dir(self.content, items[0]['content_id']) / 'item.json')['publish_at'])

    def test_partial_approval_only_range_and_unapproved_cannot_release(self):
        manifest, items, _ = self.prepared(3)
        approved = approve_range(self.content, self.config, manifest['batch_id'], '2026-10-01', '2026-10-02')
        self.assertEqual(len(approved), 2)
        remaining = read_json(item_dir(self.content, items[2]['content_id']) / 'item.json')
        self.assertEqual(remaining['status'], 'READY_FOR_REVIEW')
        with self.assertRaisesRegex(Blocked, 'EXPLICIT_APPROVAL_REQUIRED'):
            build_release(self.content, remaining, self.config)
        self.assertEqual(self.state.state['queue'], {})

    def test_choose_b_and_reorder_only_one_product_revokes_approval(self):
        _, items, _ = self.prepared(2)
        other = item_dir(self.content, items[1]['content_id']) / 'item.json'
        before = file_hash(other)
        item = approve(self.content, items[0], self.config)
        original_b = read_json(item_dir(self.content, item['content_id']) / 'caption_candidates.json')['candidates'][1]['caption']
        gen = fixtures.FixtureGenerator()
        updated = revise_one(self.content, item, self.config, gen, selected_key='B', photo_ids=list(reversed(item['selected_photo_ids'])))
        self.assertEqual(updated['status'], 'READY_FOR_REVIEW')
        self.assertEqual(updated['approval_state'], 'PENDING')
        self.assertEqual((item_dir(self.content, item['content_id']) / 'selected_caption.txt').read_text(encoding='utf-8'), original_b)
        self.assertEqual([s for s, _, _ in gen.calls], ['qa'])
        self.assertEqual(file_hash(other), before)

    def test_wrong_color_wrong_mineral_and_unselected_candidate_are_blocked(self):
        _, items, _ = self.prepared()
        item = items[0]
        folder = item_dir(self.content, item['content_id'])
        grounding, basis = read_json(folder / 'product_grounding.json'), read_json(folder / 'caption_basis.json')
        for caption, expected in [('海藍寶，濃綠色', 'WRONG_COLOUR:綠'), ('紫水晶，藍白交錯', 'UNPROVIDED_MINERAL:紫水晶')]:
            self.assertIn(expected, caption_errors(caption, item, grounding, basis))
        candidate = read_json(folder / 'caption_candidates.json')
        candidate['candidates'][2]['caption'] += ' 紫水晶'
        save_json(folder / 'caption_candidates.json', candidate)
        with self.assertRaisesRegex(Blocked, 'CAPTION_QA_FAILED_OR_STALE'):
            check_prepared(self.content, item)

    def test_publish_uses_reviewed_saved_caption_without_generator(self):
        _, items, _ = self.prepared()
        item = approve(self.content, items[0], self.config)
        pack = stage_release(self.repo, self.content, item, self.config)
        caption = (self.repo / pack['caption_path']).read_text(encoding='utf-8')
        meta = fixtures.FakeMeta()
        with patch('automation.generator.CodexBatchGenerator.generate', side_effect=AssertionError('NO AI AT PUBLISH')):
            self.publisher(meta).publish(pack)
        self.assertEqual(next(body['caption'] for edge, body in meta.posts if 'caption' in body), caption)
        before = len(meta.posts)
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(len(meta.posts), before)

    def test_pause_blocks_approved_carousel_without_network_posts(self):
        _, items, _ = self.prepared()
        item = approve(self.content, items[0], self.config)
        pack = stage_release(self.repo, self.content, item, self.config)
        self.state.state['paused'] = True
        meta = fixtures.FakeMeta()
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(meta.posts, [])

    def test_declared_metadata_and_date_edit_only_target_requeues_review(self):
        manifest, items, _ = self.prepared(2)
        other = item_dir(self.content, items[1]['content_id']) / 'item.json'
        before = file_hash(other)
        approve(self.content, items[0], self.config)
        edited = update_product(self.content, self.config, manifest['batch_id'], 'BB001', {'price': 3280, 'publish_date': '2026-10-04'})
        self.assertEqual(edited['status'], 'DRAFT')
        self.assertEqual(edited['publish_at'], '2026-10-04T10:00:00+08:00')
        self.assertEqual(edited['user_provided']['price'], 3280)
        self.assertEqual(file_hash(other), before)
        self.assertFalse(edited.get('approval'))
        self.assertEqual(resolve_item(self.content, 'BB001')['content_id'], edited['content_id'])

    def test_swapped_asset_binding_fails_before_approval(self):
        _, items, _ = self.prepared(2)
        item = copy.deepcopy(items[0])
        item['photos'][0] = items[1]['photos'][0]
        with self.assertRaisesRegex(Blocked, 'BATCH_PHOTO_BINDING_MISMATCH'):
            assert_batch_binding(self.content, item)

    def test_default_time_must_be_explicit_config_not_guessed(self):
        self.config['posting'].pop('default_publish_time', None)
        with self.assertRaisesRegex(Blocked, 'DEFAULT_PUBLISH_TIME_REQUIRED'):
            parse_intake('BB001 海藍寶 10/1', self.config)

    def test_confirmed_ten_am_default_and_single_override_do_not_change_brand(self):
        from automation.core import brand_config
        config = brand_config('baobao')
        original = copy.deepcopy(config)
        rows = parse_intake('BB001 海藍寶 10/1\nBB002 綠碧璽 10/2 19:30\nBB003 紫水晶 10/3', config, year=2026)['products']
        self.assertEqual([p['publish_time'] for p in rows], ['10:00', '19:30', '10:00'])
        self.assertEqual(config['posting']['timezone'], 'Asia/Taipei')
        self.assertEqual(config, original)

    def test_documented_intake_template_parses_without_yaml(self):
        self.config['posting']['default_publish_time'] = '20:00'
        rows = parse_intake('這批排 10/1～10/14。\nBB001：海藍寶，10/1，附這條的六張照片。\nBB002：綠碧璽，10/2，附這條的六張照片。', self.config, year=2026)['products']
        self.assertEqual([p['crystal_name'] for p in rows], ['海藍寶', '綠碧璽'])
        self.assertTrue(all(not p['issues'] for p in rows))

    def test_batch_cli_prepare_does_not_approve_or_schedule(self):
        manifest = self.intake()
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'batch', 'prepare', manifest['batch_id']])
        with patch('automation.cli.brand_config', return_value=self.config), \
             patch('automation.cli.CodexBatchGenerator', return_value=fixtures.FixtureGenerator()), \
             patch('automation.publisher.MetaClient', return_value=fixtures.FakeMeta()), \
             patch('automation.cli.GitHubJournal', side_effect=AssertionError('NO QUEUE BEFORE APPROVAL')):
            result = run(args)
        self.assertEqual(result['items'][0]['status'], 'READY_FOR_REVIEW')
        self.assertFalse(result['approval_granted'])
        self.assertEqual(result['api_post_requests_sent'], 0)

    def test_poor_photo_exclusion_reason_is_visible_and_not_deleted(self):
        manifest = self.intake()
        class PoorPhoto(fixtures.FixtureGenerator):
            def generate(self, stage, *args):
                result = super().generate(stage, *args)
                if stage == 'grounding':
                    result['photo_reviews'][-1].update(usable=False, sharpness='明顯模糊', issues=['明顯模糊'], selection_reason='建議排除此張，商品輪廓模糊。')
                    result['selected_photo_ids'] = result['selected_photo_ids'][:-1]
                return result
        items = prepare_batch(self.content, self.config, manifest['batch_id'], PoorPhoto)
        self.assertEqual(items[0]['status'], 'READY_FOR_REVIEW')
        self.assertEqual(len(items[0]['photos']), 6)
        self.assertEqual(len(items[0]['selected_photo_ids']), 5)
        page = render_preview(self.content, self.config).read_text(encoding='utf-8')
        self.assertIn('RECOMMEND_EXCLUDE', page)
        self.assertIn('商品輪廓模糊', page)

    def test_ambiguous_row_does_not_block_other_product(self):
        _, items, _ = self.prepared(2, text='Batch 2026-10-01～2026-10-14\nBB001 海藍寶 10/1 10/2\nBB002 海藍寶 10/3')
        self.assertEqual(items[0]['status'], 'NEEDS_INFO')
        self.assertIn('AMBIGUOUS_PUBLISH_DATE', items[0]['prepare_errors'])
        self.assertEqual(items[1]['status'], 'READY_FOR_REVIEW')

    def test_approval_range_with_unready_product_changes_no_approvals(self):
        manifest, items, _ = self.prepared(2, text='Batch 2026-10-01～2026-10-14\nBB001 海藍寶 10/1\nBB002 10/2')
        with self.assertRaisesRegex(Blocked, 'RANGE_CONTAINS_ITEM_NOT_READY'):
            approve_range(self.content, self.config, manifest['batch_id'], '2026-10-01', '2026-10-02')
        self.assertIsNone(read_json(item_dir(self.content, items[0]['content_id']) / 'item.json')['approval'])

    def test_late_photo_group_can_be_added_without_rebuilding_other_products(self):
        manifest = self.intake(1, text='Batch 2026-10-01～2026-10-14\nBB001 海藍寶 10/1\nBB002 綠碧璽 10/2')
        items = prepare_batch(self.content, self.config, manifest['batch_id'], fixtures.FixtureGenerator)
        other = item_dir(self.content, items[0]['content_id']) / 'item.json'
        before = file_hash(other)
        new = self.root / 'new-photos'
        new.mkdir()
        Image.new('RGB', (700, 900), (35, 130, 70)).save(new / 'new.jpg')
        item = add_photos(self.content, self.config, manifest['batch_id'], 'BB002', new)
        self.assertEqual(item['content_id'], manifest['products'][1]['content_id'])
        self.assertEqual(len(item['photos']), 1)
        self.assertEqual(file_hash(other), before)
        self.assertFalse(refresh_batch(self.content, manifest['batch_id'])['products'][1]['issues'])

    def test_external_pause_variable_blocks_even_if_journal_resumed(self):
        _, items, _ = self.prepared()
        pack = stage_release(self.repo, self.content, approve(self.content, items[0], self.config), self.config)
        meta = fixtures.FakeMeta()
        with patch.dict('os.environ', {'PAUSE_ALL_BAOBAO_PUBLISHING': 'true'}), self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(meta.posts, [])

    def test_maiocha_entry_cannot_call_batch_intake_or_prepare(self):
        from automation.core import brand_config
        config = brand_config('maiocha')
        args = parser().parse_args(['--brand', 'maiocha', '--repo', str(self.repo), '--workspace', str(self.root), 'batch', 'prepare', 'example'])
        with patch('automation.cli.brand_config', return_value=config), self.assertRaisesRegex(Blocked, 'MAIOCHA_USE_PRESERVED_LEGACY_ENTRY'):
            run(args)


if __name__ == '__main__':
    unittest.main()
