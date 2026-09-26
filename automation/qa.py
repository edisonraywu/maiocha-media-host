from __future__ import annotations

import re

import jsonschema

from .core import Blocked, digest, text_hash
from .schemas import SCHEMAS, QA_KEYS

MINERALS = ('海藍寶', '綠碧璽', '碧璽', '紫水晶', '超七', '拉利瑪', '月光石', '太陽石', '拉長石',
            '螢石', '粉晶', '白水晶', '黃水晶', '茶晶', '黑曜石', '虎眼石', '草莓晶', '鈦晶',
            '髮晶', '髮水晶', '天河石', '石榴石', '摩根石', '舒俱徠', '翡翠', '和田玉', '孔雀石',
            '橄欖石', '托帕石', '青金石', '藍晶石', '紅紋石', '磷灰石', '綠幽靈', '幽靈水晶')
UNSUPPORTED = ('收藏級', '頂級', '極稀有', '高冰', '無瑕', '晶體超乾淨', '5A', '天然無處理',
               '無燒', '無染', '無注膠', '招財保證', '開運保證', '治療', '醫療', '療效', '改善失眠',
               '招財', '轉運', '保證開運', '保證招財', '證書', '產地', '礦區', '市場價值')
COLOURS = {'藍': ('藍',), '綠': ('綠',), '粉': ('粉色', '粉紅', '淡粉', '粉粉嫩'), '紫': ('紫',),
           '白': ('白色', '乳白', '奶白', '霧白'), '黑': ('黑色', '墨黑'), '灰': ('灰色', '灰藍', '灰白'),
           '黃': ('黄色', '黃色', '淡黃'), '金': ('金色', '暖金'), '茶': ('茶色',),
           '棕': ('棕', '褐'), '紅': ('紅色', '深紅', '酒紅'), '橙': ('橙', '橘色')}


def validate(stage: str, value: dict, item: dict) -> None:
    try:
        jsonschema.validate(value, SCHEMAS[stage])
    except jsonschema.ValidationError:
        raise Blocked('INVALID_' + stage.upper() + '_SCHEMA') from None
    if value['content_id'] != item['content_id'] or value['input_hash'] != item['input_hash']:
        raise Blocked('CROSS_PRODUCT_GENERATOR_OUTPUT')


def grounding_errors(grounding: dict, item: dict) -> list[str]:
    validate('grounding', grounding, item)
    errors = []
    ids = {p['photo_id'] for p in item['photos']}
    reviews = grounding['photo_reviews']
    if {p['photo_id'] for p in reviews} != ids or len(reviews) != len(ids):
        errors.append('PHOTO_REVIEWS_NOT_EXACT')
    selected = grounding['selected_photo_ids']
    if not 1 <= len(selected) <= 10 or len(set(selected)) != len(selected) or not set(selected) <= ids:
        errors.append('INVALID_PHOTO_SELECTION')
    review_map = {p['photo_id']: p for p in reviews}
    for key in selected:
        p = review_map.get(key, {})
        if not p.get('usable') or not p.get('colour_reliable') or not p.get('same_product') or p.get('product_count') != 1:
            errors.append('SELECTED_PHOTO_UNRELIABLE:' + key)
    # Contradictory identities cannot be hidden merely by dropping the other product from a carousel.
    if any(not p['same_product'] or p['product_count'] > 1 for p in reviews):
        errors.append('PRODUCT_IDENTITY_AMBIGUOUS')
    facts = grounding['facts']
    if not facts or len({f['fact_id'] for f in facts}) != len(facts):
        errors.append('MISSING_UNIQUE_VISUAL_FACTS')
    for fact in facts:
        if not fact['evidence_photo_ids'] or not set(fact['evidence_photo_ids']) <= ids:
            errors.append('FACT_MISSING_PHOTO_EVIDENCE')
    if not grounding['visual_observations']['dominant_colors']:
        errors.append('PRODUCT_COLOUR_UNKNOWN')
    if grounding['grounding_status'] != 'PASS':
        errors.append('GROUNDING_NEEDS_INFO')
    return errors


def caption_errors(caption: str, item: dict, grounding: dict, basis: dict, candidate: dict | None = None) -> list[str]:
    errors = []
    if not caption.strip() or len(caption) > 2200:
        errors.append('CAPTION_EMPTY_OR_TOO_LONG')
    if len(re.findall(r'#\S+', caption)) > 30:
        errors.append('TOO_MANY_HASHTAGS')
    provided = item['user_provided']
    supplied_name = str(provided.get('crystal_name') or '')
    # Mineral nouns must be explicitly supplied, never inferred from the image.
    for name in MINERALS:
        if name in caption and name not in supplied_name and name not in str(provided.get('product_name') or ''):
            errors.append('UNPROVIDED_MINERAL:' + name)
    provided_text = ' '.join(str(provided.get(k) or '') for k in ('product_name', 'crystal_name', 'notes'))
    for phrase in UNSUPPORTED:
        if phrase.lower() in caption.lower():
            # User notes do not authorize medical or guaranteed-benefit marketing.
            if phrase in ('治療', '醫療', '療效', '改善失眠', '招財', '轉運', '招財保證', '開運保證', '保證開運', '保證招財') or phrase.lower() not in provided_text.lower():
                errors.append('UNSUPPORTED_CLAIM:' + phrase)
    colors = set(grounding['visual_observations']['dominant_colors'] + grounding['visual_observations']['secondary_colors'])
    # Avoid a mineral's written name being mistaken for a visible colour claim.
    descriptive = caption
    for name in (provided.get('product_name'), provided.get('crystal_name')):
        if name:
            descriptive = descriptive.replace(str(name), '')
    for family, words in COLOURS.items():
        if family not in colors and any(word in descriptive for word in words):
            errors.append('WRONG_COLOUR:' + family)
    transparent = grounding['visual_observations']['visual_transparency_appearance']
    if re.search(r'通透|透亮|透明|透光|玻璃', caption) and transparent not in ('透明感', '半透明感'):
        errors.append('UNSUPPORTED_TRANSPARENCY')
    if transparent == '半透明感' and re.search(r'完全透明|全透明|像玻璃一樣通透', caption):
        errors.append('EXAGGERATED_TRANSPARENCY')
    if grounding['visual_observations']['perceived_brightness'] == '深暗' and re.search(r'淡淡|清透|明亮透明', descriptive):
        errors.append('BRIGHTNESS_MISMATCH')
    if len(colors) >= 3 and ('單一色' in caption or '純色' in caption):
        errors.append('MULTICOLOUR_REDUCED_TO_ONE')
    for match in re.finditer(r'(?:NT\$|NTD|\$|售價\s*[:：]?|價格\s*[:：]?)\s*([\d,]+)', caption, re.I):
        if provided.get('price') is None or match[1].replace(',', '') != str(provided['price']).replace(',', ''):
            errors.append('UNPROVIDED_PRICE')
    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:mm|毫米)', caption, re.I):
        if provided.get('bead_size') is None or match[1] not in str(provided['bead_size']):
            errors.append('UNPROVIDED_BEAD_SIZE')
    for match in re.finditer(r'(?:庫存|剩|僅剩)\s*(\d+)', caption):
        if provided.get('stock') is None or match[1] != str(provided['stock']):
            errors.append('UNPROVIDED_STOCK')
    for match in re.finditer(r'\d+(?:\.\d+)?', caption.replace(',', '')):
        if not any(match[0] in str(v).replace(',', '') for v in provided.values() if v is not None):
            errors.append('UNPROVIDED_NUMBER')
    if basis['user_provided_crystal'] != provided.get('crystal_name'):
        errors.append('BASIS_CRYSTAL_MISMATCH')
    facts = {f['fact_id']: f for f in grounding['facts']}
    selected = set(grounding['selected_photo_ids'])
    if candidate:
        visual_claims = 0
        for claim in candidate['claims']:
            if not claim['text'] or claim['text'] not in caption:
                errors.append('CLAIM_NOT_IN_CAPTION')
            references = claim['references']
            if claim['source'] == 'visual':
                visual_claims += 1
                if not references or any(r not in facts or not set(facts[r]['evidence_photo_ids']) & selected for r in references):
                    errors.append('CLAIM_WITHOUT_SELECTED_PHOTO')
            elif claim['source'] == 'user_provided':
                if not references or any(not provided.get(r) for r in references):
                    errors.append('CLAIM_WITHOUT_USER_DATA')
            elif claim['source'] == 'imagery':
                if not references or not set(references) <= set(basis['candidate_imagery']):
                    errors.append('IMAGERY_WITHOUT_BASIS')
        if not visual_claims:
            errors.append('GENERIC_CAPTION_NO_VISUAL_CLAIM')
    return sorted(set(errors))


def qa_report(item: dict, grounding: dict, basis: dict, captions: dict, vision: dict) -> dict:
    validate('basis', basis, item)
    validate('captions', captions, item)
    validate('qa', vision, item)
    candidates = captions['candidates']
    errors = grounding_errors(grounding, item)
    if len(candidates) != 3 or {c['key'] for c in candidates} != {'A', 'B', 'C'}:
        errors.append('THREE_CANDIDATES_REQUIRED')
    if len({c['caption'] for c in candidates}) != 3:
        errors.append('CANDIDATES_IDENTICAL')
    chosen = next((c for c in candidates if c['key'] == captions['selected_key']), None)
    if chosen is None:
        raise Blocked('SELECTED_CAPTION_MISSING')
    caption = chosen['caption']
    errors += caption_errors(caption, item, grounding, basis, chosen)
    if not set(basis['dominant_color']) == set(grounding['visual_observations']['dominant_colors']):
        errors.append('BASIS_COLOUR_MISMATCH')
    if not basis['evidence_fact_ids'] or not set(basis['evidence_fact_ids']) <= {f['fact_id'] for f in grounding['facts']}:
        errors.append('BASIS_WITHOUT_VISUAL_EVIDENCE')
    if vision['caption_hash'] != text_hash(caption) or vision['selected_photo_ids'] != grounding['selected_photo_ids']:
        errors.append('STALE_VISUAL_QA')
    if vision['result'] != 'PASS' or not all(vision['checks'].values()):
        errors.append('IMAGE_VS_CAPTION_FAILED')
    styles = basis['content_style']
    if styles == '上手日常' and not any(p['wearing'] and p['photo_id'] in grounding['selected_photo_ids'] for p in grounding['photo_reviews']):
        errors.append('NO_WEARING_PHOTO')
    if styles in ('新品', '貓咪品牌元素', '已查證小知識'):
        errors.append('STYLE_REQUIRES_SEPARATELY_VERIFIED_INPUT')
    return {'brand': item['brand'], 'content_id': item['content_id'], 'input_hash': item['input_hash'],
            'result': 'FAIL' if errors else 'PASS', 'errors': sorted(set(errors)),
            'checks': vision['checks'], 'caption_hash': text_hash(caption),
            'grounding_hash': digest(grounding), 'basis_hash': digest(basis), 'candidates_hash': digest(captions),
            'vision_qa_hash': digest(vision), 'selected_photo_ids': grounding['selected_photo_ids']}

