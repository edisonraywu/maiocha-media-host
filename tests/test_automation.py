"""Synthetic fixtures only. Passing these tests is NOT a live product/Meta acceptance."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import yaml
from PIL import Image, ImageDraw

from automation.calendar import plan_calendar
from automation.core import REPO, Blocked, brand_config, credentials, digest, file_hash, inside, item_dir, read_json, save_json, text_hash
from automation.ingest import ingest, ingest_one
from automation.journal import LocalTestJournal, claim
from automation.network import ApiFailure, MetaClient
from automation.pipeline import check_prepared, prepare, prepare_one
from automation.preview import render_preview
from automation.publisher import Publisher, preflight
from automation.qa import caption_errors
from automation.release import approve, build_release, stage_release, validate_release
from automation.schemas import QA_KEYS


class FixtureGenerator:
    def __init__(self, wrong_colour=False, wrong_product=False, bad_qa=False, unusable=False):
        self.calls = []
        self.wrong_colour, self.wrong_product, self.bad_qa, self.unusable = wrong_colour, wrong_product, bad_qa, unusable

    def generate(self, stage, payload, photos, directory):
        self.calls.append((stage, payload['content_id'], len(photos)))
        base = {k: payload[k] for k in ('content_id', 'input_hash')}
        if self.wrong_product:
            base['content_id'] = 'baobao-OTHER'
        ids = payload['photo_ids']
        if stage == 'grounding':
            return dict(base, grounding_status='NEEDS_INFO' if self.unusable else 'PASS',
                visual_observations={'dominant_colors': ['藍'], 'secondary_colors': ['白'], 'color_description': '灰藍與白色相間',
                    'perceived_brightness': '中等', 'visual_transparency_appearance': '不透明感',
                    'visible_surface_appearance': '照片表面有局部亮點', 'visible_patterns': ['白色區塊'],
                    'visual_contrast': '中', 'overall_visual_tone': '偏冷', 'photo_lighting': '柔和側光',
                    'wearing_scene': '沒有上手', 'visual_keywords': ['藍', '白', '側光']},
                facts=[{'fact_id': 'blue', 'description': '商品可見藍色', 'evidence_photo_ids': ids},
                       {'fact_id': 'white', 'description': '有白色區塊', 'evidence_photo_ids': ids}],
                photo_reviews=[{'photo_id': k, 'usable': not self.unusable, 'issues': [], 'composition': '全貌',
                   'dominant_colors': ['藍'], 'lighting': '側光', 'colour_reliable': True, 'wearing': False,
                   'close_up': False, 'full_view': True, 'cover_score': 80, 'product_count': 1, 'same_product': True} for k in ids],
                selected_photo_ids=ids[:10], issues=[])
        if stage == 'basis':
            return dict(base, dominant_color=['藍'], secondary=['白'], light='側光', visual_mood=['偏冷'],
                user_provided_crystal=payload['user_provided']['crystal_name'], candidate_imagery=['雨後'],
                rejected_imagery=['夕陽'], reason='照片中藍白相間，光偏冷。', evidence_fact_ids=['blue', 'white'], content_style='商品主角')
        if stage == 'captions':
            word = '綠' if self.wrong_colour else '藍'
            captions = [f'這一串的{word}，和白色交錯。\n今天想多看它一眼。',
                        f'{word}與白，像雨後窗邊。\n這一串有自己的層次。',
                        f'今天戴{word}。\n白色藏在這一串裡。']
            return dict(base, candidates=[{'key': key, 'caption': text, 'hook': text.split('\n')[0], 'structure': key,
               'claims': [{'text': word, 'source': 'visual', 'references': ['blue']},
                          {'text': '白色' if '白色' in text else '白', 'source': 'visual', 'references': ['white']}],
               'product_fit_score': 90, 'reason': '保留這一串的藍與白'} for key, text in zip('ABC', captions)],
               selected_key='A', selection_reason='直接寫出商品特色')
        if stage == 'qa':
            checks = {key: True for key in QA_KEYS}
            if self.bad_qa:
                checks['product_specific'] = False
            return dict(base, caption_hash=payload['caption_hash'], selected_photo_ids=payload['selected_photo_ids'],
                        checks=checks, issues=[], result='FAIL' if self.bad_qa else 'PASS')
        raise AssertionError(stage)


class HostedFiles:
    def __init__(self, repo, config, fail=False):
        self.repo, self.config, self.fail = repo, config, fail
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if self.fail:
            raise ApiFailure('HOSTING_TEST_UNAVAILABLE', 503, True)
        prefix = self.config['hosting']['base_url'] + '/'
        if not url.startswith(prefix):
            raise AssertionError('unexpected host')
        return (self.repo / url[len(prefix):]).read_bytes(), 'image/jpeg'


class FakeMeta:
    def __init__(self, wrong=False, fail_publish=False, fail_create=False, after_create=None):
        self.posts, self.verifications, self.containers = [], 0, 1000
        self.wrong, self.fail_publish, self.fail_create, self.after_create = wrong, fail_publish, fail_create, after_create

    def verify_account(self):
        self.verifications += 1
        if self.wrong:
            raise Blocked('LIVE_ACCOUNT_MISMATCH')
        return {'verified': True}

    def post(self, edge, body):
        self.posts.append((edge, body))
        if edge == 'media_publish' and self.fail_publish:
            raise ApiFailure('NETWORK_UNAVAILABLE', transient=True)
        if edge == 'media' and self.fail_create:
            raise ApiFailure('NETWORK_UNAVAILABLE', transient=True)
        self.containers += 1
        if self.after_create and edge == 'media':
            self.after_create()
        return {'id': str(self.containers)}

    def wait_container(self, cid):
        return None


class PipelineTests(unittest.TestCase):
    def setUp(self):
        local = Path.cwd() / '.local' / 'tests'
        local.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=local)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.content = self.root / 'content' / 'baobao'
        self.content.mkdir(parents=True)
        self.config = brand_config('baobao')
        self.config['target'] = {'instagram_user_id': '222', 'facebook_page_id': '333', 'username': 'fixture.baobao'}
        self.config['posting']['defaults_need_review'] = False
        self.state = LocalTestJournal()
        self.state.state.update(paused=False, production_ready=True, test_verification={'target': self.config['target']})
        self.env = patch.dict(os.environ, {self.config['env'][k]: v for k, v in dict(self.config['target'], token='fixture-not-a-real-token').items()})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def product(self, name='one', count=1, data=None):
        folder = self.content / 'inbox' / name
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            im = Image.new('RGB', (800, 1000), (80 + index * 9, 130, 170))
            ImageDraw.Draw(im).rectangle((index + 80, 80, 600, 350), fill='white')
            im.save(folder / f'{index:02d}.jpg')
        if data is not None:
            (folder / 'product.yaml').write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
        return folder

    def prepared(self, count=1, data=None, generator=None, name='one'):
        folder = self.product(name, count, data)
        item = ingest_one(self.content, folder, 'baobao')
        item = prepare_one(self.content, item, self.config, generator or FixtureGenerator(), [])
        return item

    def release(self, count=1):
        item = self.prepared(count)
        self.assertEqual(item['status'], 'READY')
        item['publish_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        save_json(item_dir(self.content, item['content_id']) / 'item.json', item)
        approve(self.content, item, self.config)
        release = stage_release(self.repo, self.content, item, self.config)
        return item, release

    def publisher(self, meta=None, fail_host=False):
        return Publisher(self.repo, self.config, self.state, meta or FakeMeta(), HostedFiles(self.repo, self.config, fail_host))

    def test_optional_metadata_never_filled_from_image(self):
        item = self.prepared()
        grounding = read_json(item_dir(self.content, item['content_id']) / 'product_grounding.json')
        self.assertEqual(grounding['user_provided']['crystal_name'], None)
        self.assertIn('price', grounding['unknown_fields'])
        self.assertEqual(item['status'], 'READY')
        report = check_prepared(self.content, item)
        self.assertEqual(report['result'], 'PASS')

    def test_product_folders_do_not_share_metadata(self):
        a = ingest_one(self.content, self.product('a', data={'price': 111, 'crystal_name': '海藍寶'}), 'baobao')
        b = ingest_one(self.content, self.product('b', data={'price': 999, 'crystal_name': '綠碧璽'}), 'baobao')
        self.assertEqual(a['user_provided']['price'], 111)
        self.assertEqual(b['user_provided']['price'], 999)
        self.assertNotEqual(a['content_id'], b['content_id'])
        wrong = prepare_one(self.content, a, self.config, FixtureGenerator(wrong_product=True), [])
        self.assertEqual(wrong['status'], 'NEEDS_INFO')

    def test_original_unchanged_and_exact_duplicates_removed(self):
        source = self.product(count=1)
        (source / 'duplicate.jpg').write_bytes((source / '00.jpg').read_bytes())
        original = file_hash(source / '00.jpg')
        item = ingest_one(self.content, source, 'baobao')
        self.assertEqual(len(item['photos']), 1)
        self.assertEqual(len(item['duplicates_removed']), 1)
        self.assertEqual(file_hash(source / '00.jpg'), original)

    def test_wrong_colour_regenerates_once_then_needs_info(self):
        gen = FixtureGenerator(wrong_colour=True)
        item = self.prepared(generator=gen)
        self.assertEqual(item['status'], 'NEEDS_INFO')
        self.assertEqual(sum(s == 'captions' for s, _, _ in gen.calls), 2)
        self.assertIn('WRONG_COLOUR:綠', item['prepare_errors'])

    def test_generic_copy_failed_by_independent_image_qa(self):
        item = self.prepared(generator=FixtureGenerator(bad_qa=True))
        self.assertEqual(item['status'], 'NEEDS_INFO')

    def test_blurry_or_ambiguous_photos_cannot_be_ready(self):
        item = self.prepared(generator=FixtureGenerator(unusable=True))
        self.assertEqual(item['status'], 'NEEDS_INFO')

    def test_unknown_mineral_price_bead_and_transparency_rejected(self):
        item = self.prepared()
        folder = item_dir(self.content, item['content_id'])
        g, b = read_json(folder / 'product_grounding.json'), read_json(folder / 'caption_basis.json')
        for caption, code in [('海藍寶', 'UNPROVIDED_MINERAL:海藍寶'), ('售價3280', 'UNPROVIDED_PRICE'),
                              ('珠徑10mm', 'UNPROVIDED_BEAD_SIZE'), ('像玻璃一樣通透', 'UNSUPPORTED_TRANSPARENCY'),
                              ('治療失眠', 'UNSUPPORTED_CLAIM:治療')]:
            self.assertIn(code, caption_errors(caption, item, g, b))

    def test_source_change_revokes_approval(self):
        item, pack = self.release()
        folder = self.content / item['source_folder']
        (folder / 'product.yaml').write_text('price: 2500', encoding='utf-8')
        changed = ingest_one(self.content, folder, 'baobao')
        self.assertEqual(changed['status'], 'DRAFT')
        self.assertNotIn('approval', changed)
        self.assertNotEqual(changed['input_hash'], item['input_hash'])

    def test_caption_manual_edit_invalidates_saved_qa(self):
        item = self.prepared()
        (item_dir(self.content, item['content_id']) / 'selected_caption.txt').write_text('漂亮的綠色', encoding='utf-8')
        with self.assertRaisesRegex(Blocked, 'CAPTION_CHANGED'):
            check_prepared(self.content, item)

    def test_batch_twenty_is_prepared_and_calendar_is_idempotent(self):
        for index in range(20):
            self.product(f'product-{index:02d}')
        gen = FixtureGenerator()
        rows = prepare(self.content, self.config, lambda: gen)
        self.assertEqual(sum(x['status'] == 'READY' for x in rows), 20)
        first = plan_calendar(self.content, self.config, datetime(2026, 10, 1, tzinfo=timezone.utc))
        second = plan_calendar(self.content, self.config, datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(first, second)
        times = [x['publish_at'] for x in first['items']]
        self.assertEqual(len(set(times)), 20)
        self.assertTrue(all(x.endswith('+08:00') for x in times))
        before = len(gen.calls)
        prepare(self.content, self.config, lambda: gen)
        self.assertEqual(len(gen.calls), before)
        self.assertTrue(render_preview(self.content, self.config).exists())

    def test_single_and_carousel_success_record_ids(self):
        item, pack = self.release(count=3)
        meta = FakeMeta()
        result = self.publisher(meta).publish_carousel(pack)
        self.assertEqual(result['status'], 'PUBLISHED')
        self.assertTrue(result['instagram_media_id'].isdigit())
        self.assertEqual([e for e, b in meta.posts].count('media_publish'), 1)
        self.assertEqual(len(meta.posts), 5)  # 3 children, one parent, one publish
        self.assertEqual(meta.verifications, 2)

    def test_no_duplicate_publish(self):
        _, pack = self.release()
        meta = FakeMeta()
        pub = self.publisher(meta)
        pub.publish(pack)
        count = len(meta.posts)
        with self.assertRaises(Blocked):
            pub.publish(pack)
        self.assertEqual(len(meta.posts), count)

    def test_missing_token_blocks_all_posts(self):
        _, pack = self.release()
        meta = FakeMeta()
        with patch.dict(os.environ, {self.config['env']['token']: ''}):
            with self.assertRaises(Blocked):
                self.publisher(meta).publish(pack)
        self.assertEqual(meta.posts, [])

    def test_maiocha_credentials_cannot_be_used_for_baobao(self):
        with patch.dict(os.environ, {'BAOBAO_IG_USER_ID': '17841423624192593'}):
            with self.assertRaisesRegex(Blocked, 'ACCOUNT_CONFIG_MISMATCH'):
                credentials(self.config)

    def test_wrong_live_username_blocks_all_posts(self):
        _, pack = self.release()
        meta = FakeMeta(wrong=True)
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(meta.posts, [])

    def test_hosting_failure_blocks_all_posts(self):
        _, pack = self.release()
        meta = FakeMeta()
        with self.assertRaises(Blocked):
            self.publisher(meta, fail_host=True).publish(pack)
        self.assertEqual(meta.posts, [])

    def test_wrong_brand_asset_namespace_blocks_even_if_hash_rebuilt(self):
        _, pack = self.release()
        pack['assets'][0]['path'] = pack['assets'][0]['path'].replace('media/baobao/', 'media/maiocha/')
        pack['release_hash'] = digest({k: v for k, v in pack.items() if k != 'release_hash'})
        with self.assertRaisesRegex(Blocked, 'NAMESPACE'):
            validate_release(self.repo, pack, self.config)

    def test_dry_run_sends_zero_posts_and_does_not_claim(self):
        _, pack = self.release()
        meta = FakeMeta()
        report = self.publisher(meta).publish(pack, dry_run=True)
        self.assertEqual(report['result'], 'PASS')
        self.assertEqual(report['api_post_requests_sent'], 0)
        self.assertEqual(meta.posts, [])
        self.assertEqual(self.state.state['items'], {})

    def test_publish_timeout_never_retries(self):
        _, pack = self.release()
        meta = FakeMeta(fail_publish=True)
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(self.state.state['items'][pack['content_id']]['status'], 'MANUAL_ACTION_REQUIRED')
        before = len(meta.posts)
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(before, len(meta.posts))

    def test_container_timeout_never_blindly_recreates(self):
        _, pack = self.release()
        meta = FakeMeta(fail_create=True)
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual(len(meta.posts), 1)
        self.assertEqual(self.state.state['items'][pack['content_id']]['status'], 'MANUAL_ACTION_REQUIRED')

    def test_concurrent_claim_is_exclusive(self):
        _, pack = self.release()
        claim(self.state, pack)
        with self.assertRaisesRegex(Blocked, 'UNRESOLVED'):
            claim(self.state, pack)

    def test_pause_stops_even_between_container_and_publish(self):
        _, pack = self.release()
        meta = FakeMeta(after_create=lambda: self.state.state.update(paused=True))
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertEqual([edge for edge, _ in meta.posts], ['media'])

    def test_production_needs_verified_live_test(self):
        _, pack = self.release()
        self.state.state['production_ready'] = False
        meta = FakeMeta()
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack)
        self.assertFalse(meta.posts)

    def test_paths_cannot_escape_product_directory(self):
        with self.assertRaises(Blocked):
            inside(self.content, '../maiocha/data.json')

    def test_future_content_not_published_by_due_runner(self):
        _, pack = self.release()
        meta = FakeMeta()
        with self.assertRaises(Blocked):
            self.publisher(meta).publish(pack, due=True)
        self.assertFalse(meta.posts)

    def test_approval_is_bound_to_schedule(self):
        item, _ = self.release()
        item['publish_at'] = '2026-12-25T20:00:00+08:00'
        with self.assertRaisesRegex(Blocked, 'APPROVAL_MISSING_OR_STALE'):
            build_release(self.content, item, self.config)


if __name__ == '__main__':
    unittest.main()

