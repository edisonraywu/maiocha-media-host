"""Synthetic mechanics only; actual product aesthetics await owner photos and feedback."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import test_automation as fixtures
from automation.batch import intake_batch, prepare_batch
from automation.calibration import (calibration_evidence, calibration_status, check_calibration, confirm_style,
    intake_calibration, prepare_calibration, receive_feedback, render_calibration_preview, session_root)
from automation.cli import parser, run
from automation.core import Blocked, digest, file_hash, item_dir, read_json, save_json, text_hash
from automation.feedback import parse_feedback
from automation.journal import claim, schedule_release
from automation.pipeline import check_prepared, prepare_one
from automation.release import approve, build_release, stage_release, validate_release
from automation.style import (PROFILE_PATH, SIGNATURE, empty_profile, load_profile, repetition_warnings,
                              save_profile, style_report)


class CalibrationGenerator(fixtures.FixtureGenerator):
    def generate(self, stage, payload, photos, directory):
        if stage != 'calibration_captions':
            return super().generate(stage, payload, photos, directory)
        self.calls.append((stage, payload['content_id'], len(photos)))
        crystal = payload['user_provided'].get('crystal_name')
        bodies = ['這一串的藍，和白色交錯。\n側光落在珠面，白色區塊就清楚了。',
                  '藍與白把視線分成幾段。\n這一串的顏色，有自己的停頓。',
                  '雨後窗邊，藍與白像遠近不同的景。\n回到手邊，是這一串交錯的色塊。',
                  '藍與白交錯。\n把這串留在手邊。',
                  '今天想戴這串藍與白。\n白色區塊讓搭配多了變化。',
                  '寶寶，來看這一串的藍與白。\n白色區塊把每個角度串在一起。']
        candidates = []
        for key, body in zip('ABCDEF', bodies):
            metadata = fixtures.fixture_style_metadata(key)
            metadata['poetic_level'] = 'medium' if key in 'BC' else 'low'
            metadata['imagery_strength'] = 'high' if key == 'C' else 'medium'
            candidates.append({'content_id': payload['content_id'], 'style_id': key, 'caption': f'{crystal}。\n{body}',
                'claims': [{'text': '藍', 'source': 'visual', 'references': ['blue']},
                           {'text': '白', 'source': 'visual', 'references': ['white']}], 'metadata': metadata})
        return {'content_id': payload['content_id'], 'input_hash': payload['input_hash'], 'candidates': candidates}


class CalibrationTests(unittest.TestCase):
    tearDown = fixtures.PipelineTests.tearDown
    product = fixtures.PipelineTests.product
    prepared = fixtures.PipelineTests.prepared
    publisher = fixtures.PipelineTests.publisher
    release = fixtures.PipelineTests.release

    def setUp(self):
        fixtures.PipelineTests.setUp(self)
        (self.content / PROFILE_PATH).unlink()

    def intake(self, count=1, text=None, session='first'):
        source = self.root / ('photos-' + session)
        source.mkdir()
        for i in range(count):
            group = source / f'BB{i + 1:03}'
            group.mkdir()
            for j in range(6):
                im = Image.new('RGB', (650, 850), (65 + i * 8, 115 + j * 8, 170))
                ImageDraw.Draw(im).ellipse((50 + i * 2, 80 + j * 3, 560, 670), outline='white', width=8)
                im.save(group / f'{j + 1:02}.jpg')
        text = text if text is not None else '\n'.join(f'BB{i+1:03} 海藍寶' for i in range(count))
        return intake_calibration(self.content, self.config, text, source, session)

    def calibrated_preview(self, count=1, text=None, generator=None):
        session = self.intake(count, text)
        generator = generator or CalibrationGenerator()
        rows = prepare_calibration(self.content, self.config, session['session_id'], lambda: generator)
        return session, rows, generator

    def test_empty_system_waits_without_creating_preferences(self):
        status = calibration_status(self.content)
        self.assertEqual(status['status'], 'CALIBRATION_WAITING_FOR_PRODUCTS')
        self.assertFalse(status['profile_exists'])
        self.assertFalse((self.content / PROFILE_PATH).exists())
        self.assertFalse(status['publication_allowed'])

    def test_one_product_six_photos_six_bound_styles_no_selected_winner(self):
        _, rows, gen = self.calibrated_preview()
        item = rows[0]
        self.assertEqual(item['status'], 'CALIBRATION_READY_FOR_REVIEW')
        root = session_root(self.content, 'first')
        folder = item_dir(root, item['content_id'])
        captions = read_json(folder / 'calibration_captions.json')
        self.assertEqual(len(item['photos']), 6)
        self.assertEqual({c['style_id'] for c in captions['candidates']}, set('ABCDEF'))
        self.assertTrue(all(c['content_id'] == item['content_id'] for c in captions['candidates']))
        self.assertNotIn('selected_key', captions)
        self.assertFalse((folder / 'selected_caption.txt').exists())
        self.assertEqual([s for s, _, _ in gen.calls][:3], ['grounding', 'basis', 'calibration_captions'])
        self.assertEqual(sum(s == 'qa' for s, _, _ in gen.calls), 6)
        self.assertEqual(check_calibration(root, item)['result'], 'PASS')
        self.assertIsNone(item['publish_at'])
        self.assertIsNone(item['approval'])

    def test_three_products_eighteen_photos_do_not_cross(self):
        _, rows, gen = self.calibrated_preview(3)
        self.assertEqual(len(rows), 3)
        all_hashes = []
        for item in rows:
            self.assertEqual(item['status'], 'CALIBRATION_READY_FOR_REVIEW')
            self.assertEqual(len(item['photos']), 6)
            self.assertTrue(all(p['content_id'] == item['content_id'] for p in item['photos']))
            all_hashes += [p['source_sha256'] for p in item['photos']]
        self.assertEqual(len(set(all_hashes)), 18)
        self.assertTrue(all(n == 6 for _, _, n in gen.calls))

    def test_more_than_three_rejected_before_intake_files_written(self):
        with self.assertRaisesRegex(Blocked, 'ONE_TO_THREE'):
            self.intake(4)
        self.assertFalse((session_root(self.content, 'first') / 'batches').exists())

    def test_calibration_missing_identity_can_be_supplied_without_schedule(self):
        from automation.batch import update_product
        self.calibrated_preview(text='BB001')
        root = session_root(self.content, 'first')
        update_product(root, self.config, 'calibration-first', 'BB001', {'crystal_name': '海藍寶'})
        rows = prepare_calibration(self.content, self.config, 'first', CalibrationGenerator)
        self.assertEqual(rows[0]['status'], 'CALIBRATION_READY_FOR_REVIEW')
        self.assertIsNone(rows[0]['publish_at'])
        with self.assertRaisesRegex(Blocked, 'CALIBRATION_CANNOT'):
            update_product(root, self.config, 'calibration-first', 'BB001', {'publish_time': '20:30'})

    def test_cross_product_same_hash_blocks_calibration(self):
        self.intake(2)
        root = session_root(self.content, 'first')
        from automation.batch import add_photos
        source = root / 'batches/calibration-first/BB001'
        extra = self.root / 'crossed'
        extra.mkdir()
        (extra / 'wrong-product.jpg').write_bytes((source / '01.jpg').read_bytes())
        add_photos(root, self.config, 'calibration-first', 'BB002', extra)
        rows = prepare_calibration(self.content, self.config, 'first', CalibrationGenerator)
        self.assertTrue(all(row['status'] == 'NEEDS_INFO' for row in rows))

    def test_identity_missing_still_grounds_but_no_final_calibration_caption(self):
        _, rows, gen = self.calibrated_preview(text='BB001')
        self.assertEqual(rows[0]['status'], 'NEEDS_INFO')
        folder = item_dir(session_root(self.content, 'first'), rows[0]['content_id'])
        self.assertIsNone(read_json(folder / 'product_grounding.json')['user_provided']['crystal_name'])
        self.assertEqual([s for s, _, _ in gen.calls], ['grounding'])
        self.assertFalse((folder / 'calibration_captions.json').exists())

    def test_wrong_crystal_in_candidate_rejected_even_if_vision_says_pass(self):
        class Wrong(CalibrationGenerator):
            def generate(self, stage, *args):
                result = super().generate(stage, *args)
                if stage == 'calibration_captions':
                    result['candidates'][2]['caption'] = result['candidates'][2]['caption'].replace('海藍寶', '綠碧璽')
                return result
        _, rows, gen = self.calibrated_preview(generator=Wrong())
        self.assertEqual(rows[0]['status'], 'NEEDS_INFO')
        self.assertEqual(sum(s == 'calibration_captions' for s, _, _ in gen.calls), 2)

    def test_wrong_colour_rejected_and_retries_once(self):
        class Wrong(CalibrationGenerator):
            def generate(self, stage, *args):
                result = super().generate(stage, *args)
                if stage == 'calibration_captions':
                    result['candidates'][0]['caption'] += '綠色森林。'
                return result
        _, rows, gen = self.calibrated_preview(generator=Wrong())
        self.assertEqual(rows[0]['status'], 'NEEDS_INFO')
        self.assertEqual(sum(s == 'calibration_captions' for s, _, _ in gen.calls), 2)

    def test_swapped_candidate_content_id_fails(self):
        class Wrong(CalibrationGenerator):
            def generate(self, stage, *args):
                result = super().generate(stage, *args)
                if stage == 'calibration_captions':
                    result['candidates'][0]['content_id'] = 'baobao-calibration-first-BB999'
                return result
        _, rows, _ = self.calibrated_preview(generator=Wrong())
        self.assertEqual(rows[0]['status'], 'NEEDS_INFO')

    def test_repeat_prepare_reuses_verified_calibration(self):
        _, rows, _ = self.calibrated_preview()
        with patch('automation.calibration.observe_product', side_effect=AssertionError('NO REGENERATION')):
            again = prepare_calibration(self.content, self.config, 'first', CalibrationGenerator)
        self.assertEqual(again, rows)

    def test_preview_all_styles_metadata_photos_and_private_feedback(self):
        _, rows, _ = self.calibrated_preview()
        path = render_calibration_preview(self.content, 'first')
        page = path.read_text(encoding='utf-8')
        self.assertEqual(page.count('<img '), 6)
        self.assertTrue(all('data-style="' + c + '"' in page for c in 'ABCDEF'))
        self.assertIn('why_it_fits_this_product', page)
        data = read_json(path.with_suffix('.json'))
        self.assertFalse(data['publication_allowed'])
        self.assertIsNone(data['style_profile'])
        self.assertIn('price', data['products'][0]['unknown_fields'])

    def test_profile_created_only_after_feedback_then_explicit_style_confirmation(self):
        self.calibrated_preview()
        self.assertIsNone(load_profile(self.content, confirmed=False))
        draft = receive_feedback(self.content, 'first', '我喜歡 B 跟 E。C 不要。emoji 不要。')
        self.assertEqual(draft['preferred_styles'], ['B', 'E'])
        self.assertEqual(draft['rejected_styles'], ['C'])
        self.assertEqual(draft['emoji_usage'], 'none')
        self.assertIsNone(load_profile(self.content))
        profile = confirm_style(self.content, 'first')
        self.assertEqual(profile['CAPTION_STYLE_CALIBRATED'], 'YES')
        self.assertEqual(load_profile(self.content)['preferred_styles'], ['B', 'E'])
        self.assertEqual(len(list(self.content.glob('items/*/item.json'))), 0)

    def test_profile_update_persists_and_preserves_prior_preferences(self):
        self.calibrated_preview()
        receive_feedback(self.content, 'first', 'B 喜歡，C 不要。')
        confirm_style(self.content, 'first')
        result = receive_feedback(self.content, 'first', '最近有點太詩意。想多一點風景感。最近不要 CTA。')
        self.assertEqual(result['preferred_styles'], ['B'])
        self.assertEqual(result['poetic_level'], 'low')
        self.assertEqual(result['imagery_strength'], 'high')
        self.assertEqual(result['cta_usage'], 'none')
        self.assertEqual(load_profile(self.content)['revision'], 2)

    def test_profile_feedback_withdraws_only_unpublished_formal_approvals(self):
        from automation.journal import schedule_release
        self.calibrated_preview()
        fixtures.confirmed_fixture_profile(self.content)
        item, pack = self.release()
        schedule_release(self.state, pack)
        item.update(status='SCHEDULED', release_hash=pack['release_hash'])
        save_json(item_dir(self.content, item['content_id']) / 'item.json', item)
        with self.assertRaisesRegex(Blocked, 'REVOKE_REMOTE'):
            receive_feedback(self.content, 'first', 'emoji 不要。')
        receive_feedback(self.content, 'first', 'emoji 不要。', journal=self.state)
        self.assertFalse(self.state.state['queue'])
        changed = read_json(item_dir(self.content, item['content_id']) / 'item.json')
        self.assertEqual(changed['status'], 'DRAFT')
        self.assertIsNone(changed['approval'])

    def test_formal_after_calibration_uses_profile_and_two_qa_layers(self):
        self.calibrated_preview()
        receive_feedback(self.content, 'first', 'B 喜歡。')
        confirm_style(self.content, 'first')
        class Preferred(fixtures.FixtureGenerator):
            def generate(self, stage, payload, *args):
                if stage == 'captions':
                    if payload['caption_style_profile']['preferred_styles'] != ['B']:
                        raise AssertionError('PROFILE NOT PASSED')
                result = super().generate(stage, payload, *args)
                if stage == 'style_qa':
                    result['metrics'] = fixtures.fixture_style_metadata('B')
                return result
        item = self.prepared(generator=Preferred())
        self.assertEqual(item['status'], 'READY_FOR_REVIEW')
        self.assertIsNone(item['approval'])
        self.assertEqual(check_prepared(self.content, item)['result'], 'PASS')

    def test_maiocha_cannot_enter_calibration_cli(self):
        from automation.core import brand_config
        args = parser().parse_args(['--brand', 'maiocha', '--workspace', str(self.root), 'calibration', 'status'])
        with patch('automation.cli.brand_config', return_value=brand_config('maiocha')):
            with self.assertRaisesRegex(Blocked, 'MAIOCHA_USE_PRESERVED'):
                run(args)

    def test_paragraph_and_tone_feedback_store_exact_examples(self):
        self.calibrated_preview()
        result = receive_feedback(self.content, 'first', 'A 的第一段 + E 的語氣。')
        self.assertEqual(result['pending_clarification'], [])
        examples = result['favorite_examples']
        self.assertTrue(any(e['style_id'] == 'A' and e['scope'] == 'first_paragraph' for e in examples))
        self.assertTrue(any(e['style_id'] == 'E' and e['role'] == 'tone_preference' for e in examples))
        self.assertTrue(all(e['content_id'].endswith('BB001') and e['text'] for e in examples))

    def test_ambiguous_feedback_never_silently_confirms(self):
        self.calibrated_preview()
        result = receive_feedback(self.content, 'first', '我喜歡這一句，但其他不要。')
        self.assertTrue(result['pending_clarification'])
        with self.assertRaisesRegex(Blocked, 'AMBIGUOUS'):
            confirm_style(self.content, 'first')
        resolved = receive_feedback(self.content, 'first', 'B 喜歡，C 不要。', resolve_pending=True)
        self.assertFalse(resolved['pending_clarification'])
        self.assertEqual(confirm_style(self.content, 'first')['CAPTION_STYLE_CALIBRATED'], 'YES')

    def test_feedback_cannot_confirm_changed_caption(self):
        _, rows, _ = self.calibrated_preview()
        receive_feedback(self.content, 'first', 'B 喜歡。')
        path = item_dir(session_root(self.content, 'first'), rows[0]['content_id']) / 'calibration_captions.json'
        candidates = read_json(path)
        candidates['candidates'][0]['caption'] += '改動'
        save_json(path, candidates)
        with self.assertRaisesRegex(Blocked, 'STALE'):
            confirm_style(self.content, 'first')

    def test_calibration_cannot_approve_even_after_style_confirmation(self):
        _, rows, _ = self.calibrated_preview()
        receive_feedback(self.content, 'first', 'B 喜歡。')
        confirm_style(self.content, 'first')
        forged = dict(rows[0], status='READY_FOR_REVIEW')
        with self.assertRaisesRegex(Blocked, 'CALIBRATION_CANNOT'):
            approve(session_root(self.content, 'first'), forged, self.config)

    def test_calibration_cannot_schedule_publish_or_test_publish_with_forged_approval(self):
        fixtures.confirmed_fixture_profile(self.content)
        _, pack = self.release()
        for purpose, cid in [('calibration', pack['content_id']), ('formal', 'baobao-calibration-first-BB001')]:
            bad = dict(pack, purpose=purpose, content_id=cid)
            for operation in (lambda: schedule_release(self.state, bad), lambda: claim(self.state, bad),
                              lambda: self.publisher().publish(bad), lambda: self.publisher().publish(bad, test_only=True)):
                with self.assertRaisesRegex(Blocked, 'CALIBRATION_CANNOT'):
                    operation()
        self.assertEqual(self.state.state['queue'], {})
        self.assertEqual(self.state.state['items'], {})

    def test_formal_batch_before_calibration_only_grounds_and_preserves_ten_am(self):
        self.intake()
        source = self.root / 'photos-first'
        batch = intake_batch(self.content, self.config, 'BB001 海藍寶 10/1', source, batch_id='october', year=2026)
        gen = CalibrationGenerator()
        rows = prepare_batch(self.content, self.config, batch['batch_id'], lambda: gen)
        self.assertEqual(rows[0]['status'], 'WAITING_FOR_CALIBRATION')
        self.assertEqual(rows[0]['publish_at'], '2026-10-01T10:00:00+08:00')
        self.assertEqual([s for s, _, _ in gen.calls], ['grounding'])
        self.assertFalse((item_dir(self.content, rows[0]['content_id']) / 'caption_candidates.json').exists())
        with self.assertRaisesRegex(Blocked, 'CAPTION_STYLE_CALIBRATION_REQUIRED'):
            approve(self.content, dict(rows[0], status='READY_FOR_REVIEW'), self.config)

    def test_calibration_cli_no_network_even_with_ready_meta(self):
        self.intake()
        args = parser().parse_args(['--repo', str(self.repo), '--workspace', str(self.root), 'calibration', 'prepare', 'first'])
        with patch('automation.cli.brand_config', return_value=self.config), \
             patch('automation.cli.CodexBatchGenerator', return_value=CalibrationGenerator()), \
             patch('automation.cli.GitHubJournal', side_effect=AssertionError('NO NETWORK')), \
             patch('automation.cli.MetaClient', side_effect=AssertionError('NO META')):
            result = run(args)
        self.assertEqual(result['items'][0]['status'], 'CALIBRATION_READY_FOR_REVIEW')
        self.assertEqual(result['api_post_requests_sent'], 0)

    def test_calibration_default_date_never_becomes_publish_date(self):
        _, rows, _ = self.calibrated_preview(text='BB001 海藍寶 10/1 19:30')
        self.assertIsNone(rows[0]['publish_at'])
        self.assertEqual(self.config['posting']['default_publish_time'], '10:00')

    def test_style_qa_drift_regenerates_once_and_blocks_ready(self):
        fixtures.confirmed_fixture_profile(self.content)
        class Drift(fixtures.FixtureGenerator):
            def generate(self, stage, *args):
                value = super().generate(stage, *args)
                if stage == 'style_qa':
                    value['checks']['not_formulaic'] = False
                    value['result'] = 'FAIL'
                return value
        gen = Drift()
        result = self.prepared(generator=gen)
        self.assertEqual(result['status'], 'NEEDS_INFO')
        self.assertIn('STYLE_DRIFT', result['prepare_errors'])
        self.assertEqual(sum(s == 'captions' for s, _, _ in gen.calls), 2)

    def test_style_profile_change_invalidates_reviewed_caption(self):
        profile = fixtures.confirmed_fixture_profile(self.content)
        item = self.prepared()
        profile['emoji_usage'] = 'none'
        save_profile(self.content, profile)
        with self.assertRaisesRegex(Blocked, 'STALE'):
            check_prepared(self.content, item)

    def test_public_release_style_qa_tampering_rejected(self):
        fixtures.confirmed_fixture_profile(self.content)
        _, pack = self.release()
        pack['style_qa']['caption_hash'] = text_hash('OTHER')
        pack['release_hash'] = digest({k: v for k, v in pack.items() if k != 'release_hash'})
        with self.assertRaisesRegex(Blocked, 'STYLE_QA_NOT_VALID'):
            validate_release(self.repo, pack, self.config)

    def test_approved_publish_uses_saved_caption_without_generator(self):
        fixtures.confirmed_fixture_profile(self.content)
        _, pack = self.release()
        reviewed = (self.repo / pack['caption_path']).read_text(encoding='utf-8')
        meta = fixtures.FakeMeta()
        with patch('automation.generator.CodexBatchGenerator', side_effect=AssertionError('NO AI AT PUBLISH')):
            self.publisher(meta).publish(pack, due=False)
        captions = [body['caption'] for _, body in meta.posts if 'caption' in body]
        self.assertEqual(captions, [reviewed])


class FeedbackAndStyleTests(unittest.TestCase):
    def examples(self):
        return [{'content_id': 'baobao-calibration-fixture-BB001', 'style_id': s, 'text': '第一段\n\n結尾',
                 'metadata': fixtures.fixture_style_metadata(s)} for s in 'ABCDEF']

    def test_local_style_adjustments_do_not_change_all_styles(self):
        parsed = parse_feedback('C 太文青。D 有點太短。', self.examples())
        self.assertEqual(parsed['style_adjustments']['C']['poetic_level'], 'low')
        self.assertEqual(parsed['style_adjustments']['D']['length'], 'longer')
        self.assertNotIn('preferred_length', parsed['values'])

    def test_mixed_likes_and_dislikes_do_not_reverse_all_styles(self):
        for text in ('我喜歡 B 跟 E，但 C 不要。', '我喜歡 B 跟 E 但 C 不要。'):
            result = parse_feedback(text, self.examples())
            self.assertEqual(result['preferred_styles'], ['B', 'E'])
            self.assertEqual(result['rejected_styles'], ['C'])
        result = parse_feedback('B喜歡C不要', self.examples())
        self.assertEqual(result['preferred_styles'], ['B'])
        self.assertEqual(result['rejected_styles'], ['C'])

    def test_favorite_and_forbidden_phrase(self):
        result = parse_feedback('我喜歡「把顏色戴出門」。不要「剛剛好」。', self.examples())
        self.assertEqual(result['favorite_phrases'], ['把顏色戴出門'])
        self.assertEqual(result['forbidden_phrases'], ['剛剛好'])

    def test_cta_signature_emoji_preferences(self):
        result = parse_feedback('emoji 可以少量。CTA 少一點。不要每篇叫人私訊。寶寶，你的礦到了可以留，但不用每篇。', self.examples())
        self.assertEqual(result['values']['emoji_usage'], 'sparse')
        self.assertEqual(result['values']['cta_usage'], 'occasional')
        self.assertEqual(result['values']['brand_signature_usage'], 'occasional')
        self.assertFalse(result['pending_clarification'])

    def test_repetition_opening_ending_imagery_cta_signature_common_words(self):
        caption = '淡淡的雨後。\n歡迎私訊。\n' + SIGNATURE
        warnings = repetition_warnings(caption, [{'caption': caption}] * 4)
        self.assertTrue({'REPEATED_OPENING', 'REPEATED_ENDING', 'REPEATED_BRAND_SIGNATURE', 'HIGH_CAPTION_SIMILARITY'} <= set(warnings))
        self.assertTrue(any('IMAGERY' in w for w in warnings))
        self.assertTrue(any('CTA' in w for w in warnings))
        self.assertTrue(any('WORDS' in w for w in warnings))

    def test_style_qa_rejects_forbidden_phrase_emoji_cta_and_signature(self):
        profile = empty_profile()
        profile.update(profile_hash='fixture', emoji_usage='none', cta_usage='none', brand_signature_usage='none', forbidden_phrases=['罐頭'])
        item = {'brand': 'baobao', 'content_id': 'baobao-fixture', 'input_hash': 'fixture', 'user_provided': {'crystal_name': '海藍寶'}}
        caption = '海藍寶罐頭私訊💙\n' + SIGNATURE
        vision = fixtures.FixtureGenerator().generate('style_qa', dict(item, photo_ids=[], caption_hash=text_hash(caption), profile_hash='fixture'), [], Path('.'))
        errors = style_report(item, caption, profile, vision, [])['errors']
        self.assertTrue({'EMOJI_NOT_ALLOWED', 'CTA_NOT_ALLOWED', 'SIGNATURE_NOT_ALLOWED', 'FORBIDDEN_PHRASE:罐頭'} <= set(errors))


if __name__ == '__main__':
    unittest.main()
