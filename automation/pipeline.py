from __future__ import annotations

from pathlib import Path

from .core import (Blocked, PRODUCT_FIELDS, atomic_bytes, digest, file_hash, inside, item_dir,
                   item_files, local_lock, now, read_json, save_json)
from .ingest import ingest, source_snapshot
from .qa import grounding_errors, qa_report, validate

PROVENANCE = ('brand', 'source_folder', 'user_provided', 'unknown_fields', 'user_declared_facts')


def assert_current(content: Path, item: dict) -> None:
    source = inside(content, item['source_folder'])
    if source.exists():
        _, _, fresh = source_snapshot(source)
        if fresh != item['input_hash']:
            raise Blocked('SOURCE_CHANGED_RUN_PREPARE')
    else:
        raise Blocked('SOURCE_FOLDER_MISSING')
    folder = item_dir(content, item['content_id'])
    for photo in item['photos']:
        if photo.get('content_id') != item['content_id'] or photo.get('asset_id') != item['content_id'] + '-' + photo['source_sha256'][:24]:
            raise Blocked('CROSS_PRODUCT_ASSET_BINDING')
        if file_hash(inside(folder, photo['original_path'])) != photo['source_sha256']:
            raise Blocked('ORIGINAL_CHANGED')
        if file_hash(inside(folder, photo['processed_path'])) != photo['processed_sha256']:
            raise Blocked('PROCESSED_ASSET_CHANGED')


def prepare_one(content: Path, item: dict, config: dict, generator, recent: list[dict]) -> dict:
    folder = item_dir(content, item['content_id'])
    if item['status'] in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
        return item
    if item.get('issues'):
        item['status'] = 'NEEDS_INFO'
        save_json(folder / 'item.json', item)
        return item
    try:
        assert_current(content, item)
        if item['status'] in ('READY', 'READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED'):
            check_prepared(content, item)
            if item['status'] == 'READY':
                item.update(status='READY_FOR_REVIEW', approval=None, approval_state='PENDING')
                save_json(folder / 'item.json', item)
            return item
    except Blocked:
        item.pop('approval', None)
        item['status'] = 'DRAFT'
    base = {'content_id': item['content_id'], 'input_hash': item['input_hash'],
            'user_provided': item['user_provided'], 'brand_voice': config['brand_voice'],
            'photo_ids': [p['photo_id'] for p in item['photos']],
            'technical_diagnostics': [{k: p[k] for k in ('photo_id', 'original_width', 'original_height', 'technical_warning')} for p in item['photos']]}
    images = [inside(folder, p['processed_path']) for p in item['photos']]
    work = folder / 'generation'
    try:
        grounding = generator.generate('grounding', base, images, work / 'observation')
        errors = grounding_errors(grounding, item)
        # User metadata and provenance are inserted by code, never accepted from AI.
        grounding.update({'brand': item['brand'], 'source_folder': item['source_folder'],
                          'user_provided': item['user_provided'],
                          'user_declared_facts': dict(item['user_provided'], **item.get('declared_schedule', {})),
                          'unknown_fields': [f for f in PRODUCT_FIELDS if item['user_provided'].get(f) is None]})
        save_json(folder / 'product_grounding.json', grounding)
        if not str(item['user_provided'].get('crystal_name') or '').strip():
            errors.append('USER_CRYSTAL_NAME_REQUIRED')
        if errors:
            item['status'], item['prepare_errors'] = 'NEEDS_INFO', errors
            item['photo_issues'] = grounding['issues']
            save_json(folder / 'item.json', item)
            return item
        # Strict schema QA validates the original model view without the provenance fields added above.
        model_grounding = {k: v for k, v in grounding.items() if k not in PROVENANCE}
        basis = generator.generate('basis', {**base, 'grounding': grounding}, images, work / 'basis')
        validate('basis', basis, item)
        basis['user_provided_facts'] = [{'field': k, 'value': str(v)} for k, v in item['user_provided'].items() if v is not None]
        basis['user_provided_facts'] += [{'field': k, 'value': str(v)} for k, v in item.get('declared_schedule', {}).items() if v is not None]
        basis['unknown_facts'] = list(grounding['unknown_fields'])
        save_json(folder / 'caption_basis.json', basis)
        item.update(status='PREPARED', approval=None, approval_state='PENDING')
        save_json(folder / 'item.json', item)
        previous_errors = []
        for attempt in range(2):
            captions = generator.generate('captions', {**base, 'grounding': grounding, 'caption_basis': basis,
                                          'recent_content': recent[-10:], 'fix_errors': previous_errors}, images, work / f'captions-{attempt}')
            validate('captions', captions, item)
            selected = next((c for c in captions['candidates'] if c['key'] == captions['selected_key']), None)
            if not selected:
                raise Blocked('SELECTED_CAPTION_MISSING')
            from .core import text_hash
            vision = generator.generate('qa', {**base, 'grounding': grounding, 'caption_basis': basis,
                              'caption': selected['caption'], 'caption_hash': text_hash(selected['caption']),
                              'selected_photo_ids': grounding['selected_photo_ids']}, images, work / f'qa-{attempt}')
            report = qa_report(item, model_grounding, basis, captions, vision)
            # Match the saved provenance-inclusive report, not only the model's own subset.
            report['grounding_hash'] = digest(grounding)
            save_json(folder / f'caption_candidates.attempt-{attempt + 1}.json', captions)
            save_json(folder / f'caption_qa.attempt-{attempt + 1}.json', report)
            save_json(folder / 'caption_candidates.json', captions)
            save_json(folder / 'vision_qa.json', vision)
            save_json(folder / 'caption_qa.json', report)
            atomic_bytes(folder / 'selected_caption.txt', selected['caption'].encode('utf-8'))
            if report['result'] == 'PASS':
                if item.get('batch_id'):
                    from .batch import assert_batch_binding
                    assert_batch_binding(content, item)
                item.update({'status': 'READY_FOR_REVIEW', 'content_type': 'SINGLE' if len(grounding['selected_photo_ids']) == 1 else 'CAROUSEL',
                             'selected_photo_ids': grounding['selected_photo_ids'], 'content_style': basis['content_style'],
                             'cover_composition': next(p['composition'] for p in grounding['photo_reviews'] if p['photo_id'] == grounding['selected_photo_ids'][0]),
                             'colour_families': grounding['visual_observations']['dominant_colors'], 'hook': selected['hook'],
                             'caption_structure': selected['structure'], 'qa_hash': digest(report),
                             'prepare_errors': [], 'prepared_at': now()})
                item['approval'] = None
                item['approval_state'] = 'PENDING'
                break
            previous_errors = report['errors']
            item.update({'status': 'NEEDS_INFO', 'prepare_errors': previous_errors})
        save_json(folder / 'item.json', item)
        return item
    except Blocked as error:
        item.update({'status': 'NEEDS_INFO', 'prepare_errors': [error.code]})
        item.pop('approval', None)
        save_json(folder / 'item.json', item)
        return item


def check_prepared(content: Path, item: dict) -> dict:
    if not str(item['user_provided'].get('crystal_name') or '').strip():
        raise Blocked('USER_CRYSTAL_NAME_REQUIRED')
    if item.get('batch_id'):
        from .batch import assert_batch_binding
        assert_batch_binding(content, item)
    assert_current(content, item)
    folder = item_dir(content, item['content_id'])
    grounding = read_json(folder / 'product_grounding.json')
    basis = read_json(folder / 'caption_basis.json')
    captions = read_json(folder / 'caption_candidates.json')
    report = read_json(folder / 'caption_qa.json')
    vision = read_json(folder / 'vision_qa.json')
    if not all((grounding, basis, captions, report, vision)):
        raise Blocked('PREPARATION_INCOMPLETE')
    if grounding.get('brand') != item['brand'] or grounding.get('user_provided') != item['user_provided']:
        raise Blocked('GROUNDING_PRODUCT_MISMATCH')
    subset = {k: v for k, v in grounding.items() if k not in PROVENANCE}
    rerun = qa_report(item, subset, basis, captions, vision)
    rerun['grounding_hash'] = digest(grounding)
    if rerun != report or report['result'] != 'PASS' or digest(report) != item.get('qa_hash'):
        raise Blocked('CAPTION_QA_FAILED_OR_STALE')
    from .core import text_hash
    if text_hash((folder / 'selected_caption.txt').read_text(encoding='utf-8')) != report['caption_hash']:
        raise Blocked('CAPTION_CHANGED_REQUIRES_IMAGE_QA')
    return report


def prepare(content: Path, config: dict, generator_factory) -> list[dict]:
    with local_lock(content):
        ingest(content, config['brand'])
        all_items = [read_json(p) for p in item_files(content)]
        generator = None
        recent = []
        results = []
        for item in all_items:
            needs_work = item['status'] in ('DRAFT', 'PREPARED', 'NEEDS_INFO') and not item.get('issues')
            if item['status'] in ('READY', 'READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED'):
                try:
                    check_prepared(content, item)
                    if item['status'] == 'READY':
                        item.update(status='READY_FOR_REVIEW', approval=None, approval_state='PENDING')
                        save_json(item_dir(content, item['content_id']) / 'item.json', item)
                except Blocked:
                    item['status'] = 'DRAFT'
                    needs_work = True
            if needs_work and generator is None:
                try:
                    generator = generator_factory()
                except Blocked as error:
                    item['status'], item['prepare_errors'] = 'NEEDS_INFO', [error.code]
                    save_json(item_dir(content, item['content_id']) / 'item.json', item)
                    results.append(item)
                    continue
            if needs_work:
                item = prepare_one(content, item, config, generator, recent)
            results.append(item)
            recent.append({k: item.get(k) for k in ('hook', 'caption_structure', 'colour_families', 'content_style')})
        save_json(content / 'prepare-report.json', {'created_at': now(), 'items': [{k: x.get(k) for k in ('content_id', 'status', 'prepare_errors')} for x in results]})
        return results


def review_caption(content: Path, item: dict, config: dict, generator):
    if item['status'] in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED'):
        raise Blocked('IMMUTABLE_OR_UNCERTAIN_PRODUCT')
    assert_current(content, item)
    folder = item_dir(content, item['content_id'])
    manual = (folder / 'selected_caption.txt').read_text(encoding='utf-8')
    grounding = read_json(folder / 'product_grounding.json')
    basis = read_json(folder / 'caption_basis.json')
    images = [inside(folder, p['processed_path']) for p in item['photos']]
    base = {'content_id': item['content_id'], 'input_hash': item['input_hash'], 'user_provided': item['user_provided'],
            'photo_ids': [p['photo_id'] for p in item['photos']], 'grounding': grounding,
            'caption_basis': basis, 'manual_caption': manual, 'brand_voice': config['brand_voice']}
    item['approval'] = None
    item['approval_state'] = 'PENDING'
    item['status'] = 'NEEDS_INFO'
    save_json(folder / 'item.json', item)
    captions = generator.generate('captions', base, images, folder / 'generation' / 'manual-caption')
    validate('captions', captions, item)
    chosen = next((x for x in captions['candidates'] if x['key'] == captions['selected_key']), None)
    if not chosen or chosen['caption'] != manual or captions['selected_key'] != 'A':
        raise Blocked('MANUAL_CAPTION_MUST_NOT_BE_CHANGED')
    from .core import text_hash
    vision = generator.generate('qa', dict(base, caption=manual, caption_hash=text_hash(manual),
                                selected_photo_ids=grounding['selected_photo_ids']), images, folder / 'generation' / 'manual-qa')
    subset = {k: v for k, v in grounding.items() if k not in PROVENANCE}
    report = qa_report(item, subset, basis, captions, vision)
    report['grounding_hash'] = digest(grounding)
    save_json(folder / 'caption_candidates.json', captions)
    save_json(folder / 'vision_qa.json', vision)
    save_json(folder / 'caption_qa.json', report)
    item['qa_hash'], item['prepare_errors'] = digest(report), report['errors']
    item['status'] = 'READY_FOR_REVIEW' if report['result'] == 'PASS' else 'NEEDS_INFO'
    item['hook'], item['caption_structure'] = chosen['hook'], chosen['structure']
    save_json(folder / 'item.json', item)
    return item


def revise_one(content: Path, item: dict, config: dict, generator, *, instructions: str = '', photo_ids: list[str] | None = None,
               selected_key: str | None = None):
    """Revise only this item; keep its original grounding/basis and every other product untouched."""
    if item['status'] in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
        raise Blocked('IMMUTABLE_OR_UNCERTAIN_PRODUCT')
    assert_current(content, item)
    folder = item_dir(content, item['content_id'])
    grounding = read_json(folder / 'product_grounding.json')
    basis = read_json(folder / 'caption_basis.json')
    if not grounding or not basis:
        raise Blocked('PREPARATION_INCOMPLETE')
    if photo_ids is not None:
        valid = {p['photo_id'] for p in grounding['photo_reviews'] if p['usable'] and p['colour_reliable']}
        if not photo_ids or len(photo_ids) > 10 or len(set(photo_ids)) != len(photo_ids) or not set(photo_ids) <= valid:
            raise Blocked('INVALID_REVIEW_PHOTO_SELECTION')
        grounding['selected_photo_ids'] = photo_ids
        for photo in grounding['photo_reviews']:
            if photo['photo_id'] in photo_ids:
                photo['selection_reason'] = '依使用者指定順序：第 ' + str(photo_ids.index(photo['photo_id']) + 1) + ' 張。'
            elif not photo['issues']:
                photo['issues'] = ['使用者指定不使用此張。']
                photo['selection_reason'] = '使用者指定不使用此張。'
        save_json(folder / 'product_grounding.json', grounding)
    item.update(status='PREPARED', approval=None, approval_state='PENDING')
    save_json(folder / 'item.json', item)
    images = [inside(folder, p['processed_path']) for p in item['photos']]
    base = {'content_id': item['content_id'], 'input_hash': item['input_hash'], 'user_provided': item['user_provided'],
            'photo_ids': [p['photo_id'] for p in item['photos']], 'grounding': grounding,
            'caption_basis': basis, 'brand_voice': config['brand_voice'], 'user_revision_request': instructions}
    subset = {k: v for k, v in grounding.items() if k not in PROVENANCE}
    previous_errors = []
    try:
        for attempt in range(2 if instructions else 1):
            captions = (generator.generate('captions', dict(base, fix_errors=previous_errors), images, folder / 'generation' / f'revision-{attempt}')
                        if instructions else read_json(folder / 'caption_candidates.json'))
            if selected_key is not None:
                if selected_key not in ('A', 'B', 'C'):
                    raise Blocked('INVALID_CAPTION_SELECTION')
                captions['selected_key'] = selected_key
                captions['selection_reason'] = '使用者指定文案 ' + selected_key + '；重新圖片 QA 後等待明確批准。'
            validate('captions', captions, item)
            chosen = next(x for x in captions['candidates'] if x['key'] == captions['selected_key'])
            from .core import text_hash
            vision = generator.generate('qa', dict(base, caption=chosen['caption'], caption_hash=text_hash(chosen['caption']),
                                        selected_photo_ids=grounding['selected_photo_ids']), images, folder / 'generation' / f'revision-qa-{attempt}')
            report = qa_report(item, subset, basis, captions, vision)
            report['grounding_hash'] = digest(grounding)
            save_json(folder / 'caption_candidates.json', captions)
            save_json(folder / 'vision_qa.json', vision)
            save_json(folder / 'caption_qa.json', report)
            atomic_bytes(folder / 'selected_caption.txt', chosen['caption'].encode('utf-8'))
            item.update(qa_hash=digest(report), prepare_errors=report['errors'], selected_photo_ids=grounding['selected_photo_ids'],
                        content_type='SINGLE' if len(grounding['selected_photo_ids']) == 1 else 'CAROUSEL',
                        cover_composition=next(p['composition'] for p in grounding['photo_reviews'] if p['photo_id'] == grounding['selected_photo_ids'][0]),
                        hook=chosen['hook'], caption_structure=chosen['structure'])
            item['status'] = 'READY_FOR_REVIEW' if report['result'] == 'PASS' else 'NEEDS_INFO'
            if report['result'] == 'PASS':
                break
            previous_errors = report['errors']
    except Blocked as error:
        item.update(status='NEEDS_INFO', prepare_errors=[error.code])
    save_json(folder / 'item.json', item)
    return item
