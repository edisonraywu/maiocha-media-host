"""Owner-confirmed private style profiles and independently checked caption style."""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
import re

import yaml

from .core import Blocked, atomic_bytes, digest, item_dir, item_files, now, read_json, read_yaml, secret_free, text_hash
from .qa import validate

STYLE_NAMES = {'A': '商品貼合型', 'B': '顏色意境型', 'C': '風景型', 'D': '極簡短句型', 'E': '日常生活型', 'F': '寶寶礦品牌型'}
PROFILE_PATH = 'config/baobao-caption-style.yaml'
SIGNATURE = '寶寶，你的礦到了。'
REPEATED_WORDS = ('淡淡的', '柔柔的', '安靜的', '像天空', '像海風', '剛剛好', '留在今天', '慢慢的', '一點光', '一點溫柔',
                  '清爽', '溫柔', '清透', '柔和', '明亮', '清澈', '深邃', '俐落', '輕盈', '濃烈', '安靜')
IMAGERY = ('天空', '海風', '雨後', '清晨', '薄霧', '森林', '樹影', '夕陽', '秋日', '月光', '窗邊', '晚霞', '深海')
CTA = re.compile(r'私訊|私信|DM|下單|立即購買|快搶|帶回家|點(?:擊)?連結|留言|購買|歡迎詢問', re.I)
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF]')


def empty_profile() -> dict:
    """An in-memory proposal, never automatically persisted as a brand preference."""
    return {'schema_version': 1, 'brand': 'baobao', 'revision': 0, 'status': 'CALIBRATION_FEEDBACK_RECEIVED',
            'CAPTION_STYLE_CALIBRATED': 'NO', 'preferred_styles': [], 'secondary_styles': [], 'rejected_styles': [],
            'preferred_length': None, 'tone': [], 'poetic_level': None, 'imagery_strength': None,
            'daily_life_level': None, 'sales_level': None, 'emoji_usage': None, 'cta_usage': None,
            'brand_signature_usage': None, 'favorite_phrases': [], 'forbidden_phrases': [],
            'favorite_examples': [], 'rejected_examples': [], 'style_adjustments': {},
            'recent_repetition_rules': {'window': 10, 'max_same_opening': 1, 'max_same_ending': 1,
                'max_same_imagery': 3, 'max_same_cta': 2, 'max_same_signature': 2, 'max_common_phrase': 3,
                'max_similarity': 0.82}, 'feedback': [], 'pending_clarification': [], 'confirmation': None}


def profile_hash(profile: dict) -> str:
    return digest({k: v for k, v in profile.items() if k != 'profile_hash'})


def save_profile(content: Path, profile: dict) -> dict:
    secret_free(profile)
    profile['profile_hash'] = profile_hash(profile)
    atomic_bytes(content / PROFILE_PATH, yaml.safe_dump(profile, allow_unicode=True, sort_keys=False).encode('utf-8'))
    return profile


def load_profile(content: Path, *, required=False, confirmed=True) -> dict | None:
    path = content / PROFILE_PATH
    if not path.exists():
        if required:
            raise Blocked('CAPTION_STYLE_CALIBRATION_REQUIRED')
        return None
    profile = read_yaml(path)
    secret_free(profile)
    if profile.get('brand') != 'baobao' or profile.get('profile_hash') != profile_hash(profile):
        raise Blocked('INVALID_CAPTION_STYLE_PROFILE')
    for key in ('preferred_styles', 'secondary_styles', 'rejected_styles'):
        if not isinstance(profile.get(key), list) or not set(profile[key]) <= set(STYLE_NAMES):
            raise Blocked('INVALID_CAPTION_STYLE_PROFILE')
    for key in ('poetic_level', 'imagery_strength', 'daily_life_level', 'sales_level'):
        if profile.get(key) not in (None, 'low', 'medium', 'high'):
            raise Blocked('INVALID_CAPTION_STYLE_PROFILE')
    for key, values in {'preferred_length': (None, 'short', 'medium', 'long'),
                        'emoji_usage': (None, 'none', 'sparse'), 'cta_usage': (None, 'none', 'occasional'),
                        'brand_signature_usage': (None, 'none', 'occasional', 'always')}.items():
        if profile.get(key) not in values:
            raise Blocked('INVALID_CAPTION_STYLE_PROFILE')
    proof = profile.get('confirmation') or {}
    valid = (profile.get('CAPTION_STYLE_CALIBRATED') == 'YES' and profile.get('status') == 'CALIBRATION_STYLE_CONFIRMED'
             and profile.get('feedback') and not profile.get('pending_clarification')
             and proof.get('source') in ('explicit_style_confirmation', 'explicit_style_feedback_update')
             and proof.get('feedback_hash') == digest(profile['feedback']))
    if confirmed and not valid:
        if required:
            raise Blocked('CAPTION_STYLE_CALIBRATION_REQUIRED')
        return None
    return profile


def require_formal_item(content: Path, item: dict) -> dict:
    if item.get('purpose') == 'calibration' or item['content_id'].startswith('baobao-calibration-'):
        raise Blocked('CALIBRATION_CANNOT_PUBLISH_OR_SCHEDULE')
    return load_profile(content, required=True)


def caption_features(text: str, crystal_name: str = '') -> dict:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    content_lines = [x for x in lines if x.strip('。！.! ') != crystal_name]
    return {'opening': (content_lines or lines or [''])[0], 'ending': (content_lines or lines or [''])[-1],
            'imagery': [word for word in IMAGERY if word in text], 'cta': CTA.findall(text),
            'signature': SIGNATURE.rstrip('。') in text, 'words': [word for word in REPEATED_WORDS if word in text],
            'emoji_count': len(EMOJI.findall(text)), 'characters': len(text), 'lines': len(lines)}


def repetition_warnings(caption: str, recent: list[dict], rules: dict | None = None, *, crystal_name='') -> list[str]:
    rules = rules or empty_profile()['recent_repetition_rules']
    recent = recent[-rules['window']:]
    current = caption_features(caption, crystal_name)
    prior = [caption_features(x['caption'], x.get('crystal_name', '')) for x in recent if x.get('caption')]
    warnings = []
    for key in ('opening', 'ending'):
        if current[key] and sum(x[key] == current[key] for x in prior) >= rules['max_same_' + key]:
            warnings.append('REPEATED_' + key.upper())
    for key, limit in (('imagery', 'max_same_imagery'), ('cta', 'max_same_cta'), ('words', 'max_common_phrase')):
        for value in current[key]:
            if sum(value in x[key] for x in prior) >= rules[limit]:
                warnings.append('REPEATED_' + key.upper() + ':' + value)
    if current['signature'] and sum(x['signature'] for x in prior) >= rules['max_same_signature']:
        warnings.append('REPEATED_BRAND_SIGNATURE')
    for old in recent:
        if old.get('caption') and SequenceMatcher(None, caption, old['caption']).ratio() >= rules['max_similarity']:
            warnings.append('HIGH_CAPTION_SIMILARITY')
            break
    return sorted(set(warnings))


def recent_captions(content: Path, *, exclude_id: str | None = None, limit=10) -> list[dict]:
    rows = []
    for path in item_files(content):
        item = read_json(path)
        if item['content_id'] == exclude_id or item.get('purpose') == 'calibration' or item['status'] in ('DRAFT', 'NEEDS_INFO', 'CANCELLED', 'WAITING_FOR_CALIBRATION'):
            continue
        caption = path.parent / 'selected_caption.txt'
        if caption.exists():
            rows.append({'content_id': item['content_id'], 'caption': caption.read_text(encoding='utf-8'),
                         'crystal_name': item['user_provided'].get('crystal_name', ''),
                         'date': item.get('published_at') or item.get('prepared_at') or item['created_at']})
    return sorted(rows, key=lambda x: x['date'])[-limit:]


def style_report(item: dict, caption: str, profile: dict, vision: dict, recent: list[dict]) -> dict:
    validate('style_qa', vision, item)
    errors = []
    features = caption_features(caption, str(item['user_provided'].get('crystal_name') or ''))
    if vision['caption_hash'] != text_hash(caption) or vision['profile_hash'] != profile['profile_hash']:
        errors.append('STALE_STYLE_QA')
    if vision['result'] != 'PASS' or not all(vision['checks'].values()):
        errors.append('STYLE_DRIFT')
    metrics = vision['metrics']
    if metrics['style_id'] in profile['rejected_styles']:
        errors.append('REJECTED_STYLE')
    preferred = profile['preferred_styles'] + profile['secondary_styles']
    if preferred and metrics['style_id'] not in preferred:
        errors.append('UNPREFERRED_STYLE')
    for phrase in profile['forbidden_phrases']:
        if phrase and phrase in caption:
            errors.append('FORBIDDEN_PHRASE:' + phrase)
    if profile['emoji_usage'] == 'none' and features['emoji_count']:
        errors.append('EMOJI_NOT_ALLOWED')
    if profile['emoji_usage'] == 'sparse' and features['emoji_count'] > 2:
        errors.append('TOO_MANY_EMOJI')
    if profile['cta_usage'] == 'none' and features['cta']:
        errors.append('CTA_NOT_ALLOWED')
    if profile['brand_signature_usage'] == 'none' and features['signature']:
        errors.append('SIGNATURE_NOT_ALLOWED')
    if profile['brand_signature_usage'] == 'always' and not features['signature']:
        errors.append('SIGNATURE_REQUIRED_BY_OWNER')
    if profile['preferred_length'] == 'short' and (features['characters'] > 160 or features['lines'] > 5):
        errors.append('STYLE_TOO_LONG')
    if profile['preferred_length'] == 'long' and features['characters'] < 100:
        errors.append('STYLE_TOO_SHORT')
    for key in ('poetic_level', 'sales_level'):
        if profile[key] == 'low' and metrics[key] == 'high':
            errors.append('STYLE_EXCESSIVE_' + key.upper())
    for example in profile.get('rejected_examples', []):
        if example.get('text') and (example['text'] in caption or SequenceMatcher(None, caption, example['text']).ratio() > .9):
            errors.append('REJECTED_EXAMPLE_REUSED')
    repeats = repetition_warnings(caption, recent, profile['recent_repetition_rules'], crystal_name=item['user_provided'].get('crystal_name', ''))
    errors += repeats
    return {'brand': item['brand'], 'content_id': item['content_id'], 'input_hash': item['input_hash'],
            'caption_hash': text_hash(caption), 'profile_hash': profile['profile_hash'], 'profile_revision': profile['revision'],
            'result': 'FAIL' if errors else 'PASS', 'errors': sorted(set(errors)), 'checks': vision['checks'],
            'metrics': metrics, 'features': features, 'repetition_warnings': repeats, 'vision_hash': digest(vision),
            'recent_hash': digest(recent)}


def run_style_qa(content: Path, item: dict, caption: str, base: dict, images: list[Path], generator, directory: Path) -> dict:
    profile = require_formal_item(content, item)
    recent = recent_captions(content, exclude_id=item['content_id'], limit=profile['recent_repetition_rules']['window'])
    vision = generator.generate('style_qa', dict(base, caption=caption, caption_hash=text_hash(caption),
                     profile_hash=profile['profile_hash'], caption_style_profile=profile, recent_captions=recent), images, directory)
    report = style_report(item, caption, profile, vision, recent)
    from .core import save_json
    folder = item_dir(content, item['content_id'])
    save_json(folder / 'style_vision_qa.json', vision)
    save_json(folder / 'style_qa_context.json', recent)
    save_json(folder / 'style_qa.json', report)
    return report


def check_style_prepared(content: Path, item: dict, caption: str) -> dict:
    profile = require_formal_item(content, item)
    folder = item_dir(content, item['content_id'])
    vision, recent, saved = (read_json(folder / name) for name in ('style_vision_qa.json', 'style_qa_context.json', 'style_qa.json'))
    if not vision or recent is None or not saved:
        raise Blocked('STYLE_QA_REQUIRED')
    rerun = style_report(item, caption, profile, vision, recent)
    if rerun != saved or rerun['result'] != 'PASS':
        raise Blocked('STYLE_QA_FAILED_OR_STALE')
    return saved
