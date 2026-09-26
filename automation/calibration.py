"""Private, non-publishable 1–3 product style calibration using the existing photo pipeline."""
from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from .batch import assert_batch_binding, batch_path, intake_batch, refresh_batch
from .core import (Blocked, atomic_bytes, digest, inside, item_dir, item_files, local_lock,
                   now, read_json, save_json, text_hash, valid_id)
from .feedback import merge_feedback, parse_feedback
from .ingest import ingest_one
from .pipeline import PROVENANCE, assert_current, observe_product
from .preview import photo_plan
from .qa import caption_errors, grounding_errors, validate
from .style import STYLE_NAMES, caption_features, load_profile, repetition_warnings, save_profile

CALIBRATION_STATES = ('CALIBRATION_SYSTEM_READY', 'CALIBRATION_WAITING_FOR_PRODUCTS', 'CALIBRATION_PREPARING',
                      'CALIBRATION_READY_FOR_REVIEW', 'CALIBRATION_FEEDBACK_RECEIVED', 'CALIBRATION_STYLE_CONFIRMED')


def session_root(content: Path, session_id: str) -> Path:
    return inside(content / 'calibration', valid_id(session_id))


def calibration_status(content: Path) -> dict:
    profile = load_profile(content, confirmed=False)
    sessions = [read_json(p) for p in sorted((content / 'calibration').glob('*/session.json'))]
    confirmed = load_profile(content) is not None
    state = ('CALIBRATION_STYLE_CONFIRMED' if confirmed else sessions[-1]['status'] if sessions
             else 'CALIBRATION_WAITING_FOR_PRODUCTS')
    result = {'system_status': 'CALIBRATION_SYSTEM_READY', 'status': state,
              'CAPTION_STYLE_CALIBRATED': 'YES' if confirmed else 'NO',
              'sessions': [{k: s.get(k) for k in ('session_id', 'status', 'product_count')} for s in sessions],
              'profile_exists': profile is not None, 'publication_allowed': False}
    save_json(content / 'calibration' / 'status.json', result)
    return result


def intake_calibration(content: Path, config: dict, text: str, source: Path, session_id: str) -> dict:
    root = session_root(content, session_id)
    batch = intake_batch(root, config, text, source, batch_id='calibration-' + session_id, purpose='calibration')
    old = read_json(root / 'session.json')
    session = old or {'session_id': session_id, 'brand': 'baobao', 'purpose': 'calibration',
        'batch_id': batch['batch_id'], 'product_count': len(batch['products']), 'created_at': now(),
        'status': 'CALIBRATION_PREPARING', 'publication_allowed': False}
    save_json(root / 'session.json', session)
    calibration_status(content)
    return session


def candidate_report(item, grounding, basis, candidate, vision):
    errors = grounding_errors({k: v for k, v in grounding.items() if k not in PROVENANCE}, item)
    validate('basis', basis, item)
    validate('qa', vision, item)
    if candidate['content_id'] != item['content_id'] or candidate['metadata']['style_id'] != candidate['style_id']:
        errors.append('CROSS_PRODUCT_OR_STYLE_OUTPUT')
    if candidate['metadata']['style_name'] != STYLE_NAMES[candidate['style_id']]:
        errors.append('STYLE_NAME_MISMATCH')
    if not candidate['metadata']['why_it_fits_this_product'].strip():
        errors.append('PRODUCT_STYLE_REASON_REQUIRED')
    errors += caption_errors(candidate['caption'], item, grounding, basis, candidate)
    if set(basis['dominant_color']) != set(grounding['visual_observations']['dominant_colors']):
        errors.append('BASIS_COLOUR_MISMATCH')
    if not basis['evidence_fact_ids'] or not set(basis['evidence_fact_ids']) <= {f['fact_id'] for f in grounding['facts']}:
        errors.append('BASIS_WITHOUT_VISUAL_EVIDENCE')
    if (vision['caption_hash'] != text_hash(candidate['caption']) or vision['selected_photo_ids'] != grounding['selected_photo_ids']):
        errors.append('STALE_VISUAL_QA')
    if vision['result'] != 'PASS' or not all(vision['checks'].values()):
        errors.append('IMAGE_VS_CAPTION_FAILED')
    features = caption_features(candidate['caption'], item['user_provided']['crystal_name'])
    if candidate['style_id'] == 'D' and not 2 <= features['lines'] <= 5:
        errors.append('MINIMAL_STYLE_REQUIRES_TWO_TO_FIVE_LINES')
    if (candidate['metadata']['cta_usage'] == 'present') != bool(features['cta']):
        errors.append('CTA_METADATA_MISMATCH')
    if (candidate['metadata']['brand_signature_usage'] == 'present') != features['signature']:
        errors.append('SIGNATURE_METADATA_MISMATCH')
    return {'content_id': item['content_id'], 'input_hash': item['input_hash'], 'style_id': candidate['style_id'],
            'caption_hash': text_hash(candidate['caption']), 'result': 'FAIL' if errors else 'PASS',
            'errors': sorted(set(errors)), 'checks': vision['checks'], 'vision': vision}


def check_calibration(root: Path, item: dict) -> dict:
    if item.get('purpose') != 'calibration' or not item['content_id'].startswith('baobao-calibration-'):
        raise Blocked('CALIBRATION_NAMESPACE_REQUIRED')
    if item.get('publish_at') or item.get('approval') or item.get('approval_state') == 'APPROVED':
        raise Blocked('CALIBRATION_CANNOT_PUBLISH_OR_SCHEDULE')
    assert_current(root, item)
    assert_batch_binding(root, item)
    folder = item_dir(root, item['content_id'])
    grounding, basis, captions, report = [read_json(folder / name) for name in
            ('product_grounding.json', 'caption_basis.json', 'calibration_captions.json', 'calibration_qa.json')]
    if not all((grounding, basis, captions, report)):
        raise Blocked('CALIBRATION_NOT_PREPARED')
    validate('calibration_captions', captions, item)
    if len(captions['candidates']) != 6 or {c['style_id'] for c in captions['candidates']} != set(STYLE_NAMES):
        raise Blocked('SIX_CALIBRATION_STYLES_REQUIRED')
    if len({c['caption'] for c in captions['candidates']}) != 6:
        raise Blocked('CALIBRATION_STYLES_IDENTICAL')
    if (grounding.get('user_provided') != item['user_provided'] or grounding.get('brand') != item['brand'] or
        report.get('grounding_hash') != digest(grounding) or report.get('basis_hash') != digest(basis) or
        report.get('candidates_hash') != digest(captions) or report.get('result') != 'PASS' or
        report.get('content_id') != item['content_id'] or report.get('input_hash') != item['input_hash']):
        raise Blocked('CALIBRATION_QA_FAILED_OR_STALE')
    for candidate in captions['candidates']:
        saved = report['styles'].get(candidate['style_id'])
        if not saved or candidate_report(item, grounding, basis, candidate, saved['vision']) != saved or saved['result'] != 'PASS':
            raise Blocked('CALIBRATION_QA_FAILED_OR_STALE')
    return report


def prepare_calibration(content: Path, config: dict, session_id: str, generator_factory) -> list[dict]:
    root = session_root(content, session_id)
    session = read_json(root / 'session.json')
    if not session:
        raise Blocked('CALIBRATION_SESSION_NOT_FOUND')
    results, generator = [], None
    with local_lock(root):
        batch = refresh_batch(root, session['batch_id'])
        for product in batch['products']:
            folder = item_dir(root, product['content_id'])
            item = None
            try:
                item = ingest_one(root, batch_path(root, batch['batch_id']) / product['product_ref'], 'baobao')
                if item.get('issues') or product.get('binding_errors'):
                    raise Blocked('CALIBRATION_PHOTO_INTAKE_NEEDS_INFO')
                if item['status'] == 'CALIBRATION_READY_FOR_REVIEW':
                    try:
                        check_calibration(root, item)
                        results.append(item)
                        continue
                    except Blocked:
                        pass
                item.update(status='CALIBRATION_PREPARING', approval=None, approval_state='PENDING', publish_at=None)
                save_json(folder / 'item.json', item)
                generator = generator or generator_factory()
                base, images, grounding, basis = observe_product(root, item, config, generator)
                assert_batch_binding(root, item)
                base.update(grounding=grounding, caption_basis=basis)
                errors = []
                for attempt in range(2):
                    try:
                        captions = generator.generate('calibration_captions', dict(base, fix_errors=errors), images,
                                                      folder / 'generation' / f'calibration-{attempt}')
                        validate('calibration_captions', captions, item)
                        if len(captions['candidates']) != 6 or {c['style_id'] for c in captions['candidates']} != set(STYLE_NAMES):
                            raise Blocked('SIX_CALIBRATION_STYLES_REQUIRED')
                        if len({c['caption'] for c in captions['candidates']}) != 6:
                            raise Blocked('CALIBRATION_STYLES_IDENTICAL')
                        reports, errors = {}, []
                        for candidate in captions['candidates']:
                            style_id = candidate['style_id']
                            vision = generator.generate('qa', dict(base, caption=candidate['caption'],
                                caption_hash=text_hash(candidate['caption']), selected_photo_ids=grounding['selected_photo_ids']),
                                images, folder / 'generation' / f'calibration-qa-{attempt}-{style_id}')
                            reports[style_id] = candidate_report(item, grounding, basis, candidate, vision)
                            errors += reports[style_id]['errors']
                        report = {'content_id': item['content_id'], 'input_hash': item['input_hash'],
                                  'grounding_hash': digest(grounding), 'basis_hash': digest(basis), 'candidates_hash': digest(captions),
                                  'styles': reports, 'result': 'FAIL' if errors else 'PASS', 'errors': sorted(set(errors))}
                        save_json(folder / 'calibration_captions.json', captions)
                        save_json(folder / 'calibration_qa.json', report)
                        save_json(folder / f'calibration_qa.attempt-{attempt + 1}.json', report)
                        if not errors:
                            break
                    except Blocked as error:
                        errors = [error.code]
                if errors:
                    raise Blocked(errors[0])
                item.update(status='CALIBRATION_READY_FOR_REVIEW', prepare_errors=[],
                            selected_photo_ids=grounding['selected_photo_ids'],
                            content_type='SINGLE' if len(grounding['selected_photo_ids']) == 1 else 'CAROUSEL', prepared_at=now())
                save_json(folder / 'item.json', item)
            except Blocked as error:
                item = item or {'content_id': product['content_id'], 'purpose': 'calibration', 'brand': 'baobao'}
                item.update(status='NEEDS_INFO', prepare_errors=[error.code], approval=None, approval_state='PENDING', publish_at=None)
                if item.get('photos'):
                    save_json(folder / 'item.json', item)
            results.append(item)
        session['status'] = ('CALIBRATION_READY_FOR_REVIEW' if all(i['status'] == 'CALIBRATION_READY_FOR_REVIEW' for i in results)
                             else 'CALIBRATION_PREPARING')
        session['items'] = [{k: i.get(k) for k in ('content_id', 'status', 'prepare_errors')} for i in results]
        save_json(root / 'session.json', session)
    render_calibration_preview(content, session_id)
    calibration_status(content)
    return results


def calibration_evidence(content: Path, session_id: str, *, content_id=None, style_id=None):
    root = session_root(content, session_id)
    session = read_json(root / 'session.json')
    if not session:
        raise Blocked('CALIBRATION_SESSION_NOT_FOUND')
    examples, reports = [], []
    for product in refresh_batch(root, session['batch_id'])['products']:
        item = read_json(item_dir(root, product['content_id']) / 'item.json')
        if not item:
            raise Blocked('CALIBRATION_NOT_PREPARED')
        report = check_calibration(root, item)
        reports.append(report)
        if content_id and content_id not in (item['content_id'], item.get('product_ref')):
            continue
        for candidate in read_json(item_dir(root, item['content_id']) / 'calibration_captions.json')['candidates']:
            if style_id and style_id != candidate['style_id']:
                continue
            examples.append({'content_id': item['content_id'], 'style_id': candidate['style_id'], 'text': candidate['caption'],
                             'metadata': candidate['metadata'], 'caption_hash': text_hash(candidate['caption'])})
    if not examples:
        raise Blocked('FEEDBACK_PRODUCT_OR_STYLE_NOT_FOUND')
    return examples, digest(reports)


def withdraw_formal_reviews(content: Path, journal=None):
    """A profile change cannot leave already queued captions publishing with stale preferences."""
    from .journal import revoke_scheduled
    items = [(p, read_json(p)) for p in item_files(content)]
    for _, item in items:
        if item.get('release_hash') and item['status'] not in ('PUBLISHED', 'CANCELLED'):
            if journal is None:
                raise Blocked('REVOKE_REMOTE_SCHEDULE_BEFORE_STYLE_UPDATE')
            revoke_scheduled(journal, item['content_id'])
    for path, item in items:
        if item['status'] not in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
            item.update(status='DRAFT', approval=None, approval_state='PENDING', prepare_errors=['STYLE_PROFILE_CHANGED_REPREPARE'])
            item.pop('release_hash', None)
            save_json(path, item)


def receive_feedback(content: Path, session_id: str, text: str, *, content_id=None, style_id=None,
                     resolve_pending=False, journal=None) -> dict:
    examples, evidence_hash = calibration_evidence(content, session_id, content_id=content_id, style_id=style_id)
    parsed = parse_feedback(text, examples)
    profile = load_profile(content, confirmed=False)
    was_confirmed = load_profile(content) is not None
    result = merge_feedback(profile, parsed, text, session_id=session_id, evidence_hash=evidence_hash, resolve_pending=resolve_pending)
    withdraw_formal_reviews(content, journal)
    if was_confirmed and not result['pending_clarification']:
        result.update(status='CALIBRATION_STYLE_CONFIRMED', CAPTION_STYLE_CALIBRATED='YES',
                      confirmation={'source': 'explicit_style_feedback_update', 'confirmed_at': now(),
                                    'feedback_hash': digest(result['feedback']), 'evidence_hash': evidence_hash})
    save_profile(content, result)
    root = session_root(content, session_id)
    session = read_json(root / 'session.json')
    session['status'] = result['status']
    save_json(root / 'session.json', session)
    render_calibration_preview(content, session_id)
    calibration_status(content)
    return result


def confirm_style(content: Path, session_id: str, *, journal=None) -> dict:
    _, evidence_hash = calibration_evidence(content, session_id)
    profile = load_profile(content, required=True, confirmed=False)
    if not profile['feedback'] or profile['pending_clarification']:
        raise Blocked('OWNER_STYLE_FEEDBACK_REQUIRED_OR_AMBIGUOUS')
    latest = profile['feedback'][-1]
    if latest['session_id'] != session_id or latest['evidence_hash'] != evidence_hash:
        raise Blocked('CALIBRATION_CHANGED_REVIEW_FEEDBACK_AGAIN')
    withdraw_formal_reviews(content, journal)
    profile.update(status='CALIBRATION_STYLE_CONFIRMED', CAPTION_STYLE_CALIBRATED='YES',
                   confirmation={'source': 'explicit_style_confirmation', 'confirmed_at': now(),
                                 'feedback_hash': digest(profile['feedback']), 'evidence_hash': evidence_hash})
    save_profile(content, profile)
    root = session_root(content, session_id)
    session = read_json(root / 'session.json')
    session['status'] = 'CALIBRATION_STYLE_CONFIRMED'
    save_json(root / 'session.json', session)
    render_calibration_preview(content, session_id)
    calibration_status(content)
    return profile


def render_calibration_preview(content: Path, session_id: str) -> Path:
    root = session_root(content, session_id)
    session = read_json(root / 'session.json')
    if not session:
        raise Blocked('CALIBRATION_SESSION_NOT_FOUND')
    out = root / 'preview'
    rows, cards, recent = [], [], []
    esc = lambda value: html.escape(str(value if value is not None else '未提供'))
    batch = refresh_batch(root, session['batch_id'])
    for product in batch['products']:
        folder = item_dir(root, product['content_id'])
        item = read_json(folder / 'item.json', {'content_id': product['content_id'], 'status': 'NEEDS_INFO', 'photos': []})
        grounding, basis, captions, qa = [read_json(folder / name, {}) for name in
            ('product_grounding.json', 'caption_basis.json', 'calibration_captions.json', 'calibration_qa.json')]
        if grounding.get('input_hash') != item.get('input_hash'):
            grounding = {}
        if basis.get('input_hash') != item.get('input_hash'):
            basis = {}
        if captions.get('input_hash') != item.get('input_hash') or not item.get('user_provided', {}).get('crystal_name'):
            captions, qa = {}, {}
        plan = photo_plan(item, grounding)
        photo_html = []
        for photo in plan:
            source = folder / (photo.get('processed_path') or photo['original_path'])
            url = quote(os.path.relpath(source, out).replace('\\', '/'), safe='/')
            photo_html.append(f'<figure><img src="{url}" loading="lazy" alt="{esc(photo["source_name"])}"><figcaption>'
                f'{esc("Cover · 01" if photo["cover"] else photo["position"] or photo["recommendation"])} · {esc(photo["source_name"])}'
                f'<br>{esc(photo["reason"])}</figcaption></figure>')
        candidates, style_html = [], []
        for candidate in sorted(captions.get('candidates', []), key=lambda c: c['style_id']):
            warnings = repetition_warnings(candidate['caption'], recent, crystal_name=product.get('crystal_name') or '')
            recent.append({'caption': candidate['caption'], 'crystal_name': product.get('crystal_name') or ''})
            candidate = dict(candidate, repetition_warnings=warnings, qa=qa.get('styles', {}).get(candidate['style_id'], {}))
            candidates.append(candidate)
            meta = ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in candidate['metadata'].items())
            style_html.append(f'<section class="style" data-style="{candidate["style_id"]}"><h3>Style {candidate["style_id"]} · '
                f'{esc(candidate["metadata"]["style_name"])}</h3><pre>{esc(candidate["caption"])}</pre><dl>{meta}</dl>'
                f'<p>Product QA：{esc(candidate["qa"].get("result"))}</p><p>用詞重複提醒：{esc(warnings or "無")}</p></section>')
        row = {'content_id': product['content_id'], 'crystal_name': product['crystal_name'], 'status': item['status'],
               'source_folder': item.get('source_folder'), 'user_provided': item.get('user_provided', {}), 'photo_plan': plan,
               'grounding': grounding, 'caption_basis': basis, 'candidates': candidates, 'qa': qa,
               'unknown_fields': grounding.get('unknown_fields', []), 'issues': item.get('prepare_errors', []) + product['issues'],
               'publication_allowed': False, 'publish_at': None}
        rows.append(row)
        cards.append(f'<article data-content-id="{esc(product["content_id"])}"><h2>{esc(product["crystal_name"])} · {esc(product["product_ref"])}</h2>'
            f'<p>{esc(product["content_id"])} · {esc(item["status"])}</p><div class="photos">{"".join(photo_html)}</div>'
            f'<details open><summary>商品觀察與文案依據</summary><pre>{esc(grounding.get("visual_observations", {}))}</pre>'
            f'<p>候選意境：{esc(basis.get("candidate_imagery"))}；排除：{esc(basis.get("rejected_imagery"))}</p>'
            f'<p>{esc(basis.get("reason"))}</p><p>使用者資料：{esc(row["user_provided"])}</p>'
            f'<p>未知：{esc(row["unknown_fields"])}</p><p>待補：{esc(row["issues"])}</p></details><div class="styles">{"".join(style_html)}</div></article>')
    profile = load_profile(content, confirmed=False)
    profile_html = ('<article><h2>你的風格回饋</h2><pre>' + esc({k: v for k, v in profile.items() if k not in ('feedback', 'favorite_examples', 'rejected_examples')}) + '</pre></article>') if profile else ''
    page = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>寶寶礦到了 · 文案風格校準</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f2eb;color:#273a39;font:16px/1.7 system-ui,"Microsoft JhengHei",sans-serif}}main{{max-width:1200px;margin:auto;padding:28px}}h1{{font-size:34px}}article,.style{{background:white;border:1px solid #deded4;border-radius:14px;padding:22px;margin:20px 0}}.photos{{display:flex;overflow:auto;gap:12px}}figure{{margin:0;flex:0 0 220px}}img{{width:100%;border-radius:8px}}figcaption{{font-size:13px}}.styles{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}dl{{display:grid;grid-template-columns:150px 1fr;font-size:13px}}dd{{margin:0;overflow-wrap:anywhere}}.notice{{background:#fff3da;padding:16px;border-left:4px solid #aa8452}}@media(max-width:700px){{.styles{{grid-template-columns:1fr}}main{{padding:14px}}}}</style>
<main><p>寶寶礦到了 · 第一次一起找語氣</p><h1>同一串，六種說法。</h1><p class="notice">先看實際商品，再比較你喜歡的表達。沒有替你選定唯一風格。此處不會排程或發布；風格確認也不等於商品發布批准。</p>
<p>可以直接說：「我喜歡 B 跟 E」「C 太文青」「emoji 不要」「品牌句可以留，但不用每篇」。</p>{profile_html}{''.join(cards)}
<footer>私人校準 Preview · 全部觀察只描述照片視覺，不代表寶石學鑑定。</footer></main></html>'''
    atomic_bytes(out / 'preview.html', page.encode('utf-8'))
    save_json(out / 'preview.json', {'session': session, 'products': rows, 'style_profile': profile, 'publication_allowed': False})
    return out / 'preview.html'
