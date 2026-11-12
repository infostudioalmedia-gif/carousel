# -*- coding: utf-8 -*-
"""تركيب برومبتات الصور بنمط رؤية الثابت: [نمط ثابت] + [قاعدة تكوين النمط] + [إطار] + [الموضوع]  +  برومبت سلبي ثابت لكل صورة."""
import json
from pathlib import Path

STYLE = json.loads((Path(__file__).parent / 'image_style.json').read_text(encoding='utf-8'))


def compose(rule, subject, w, h):
    ratio = '%.2f:1' % (w / float(h))
    pos = ' '.join(x for x in [STYLE['positive_base'], (rule or '').strip(),
                               'Frame: %dx%d px (aspect ratio %s).' % (w, h, ratio),
                               'Subject (the only variable part): %s' % (subject or '').strip()] if x)
    return {'positive': pos, 'negative': STYLE['negative']}


def markdown(title, style_label, slots):
    out = ['# برومبتات الصور — %s' % title, '', 'النمط: **%s** · نمط الصور: **%s** (ثابت لكل الكاروسيلات؛ المتغير هو الموضوع فقط)' % (style_label, STYLE['name']), '']
    for s in slots:
        out += ['## %s — %s' % (s['label'], s['ratio']), '', '**الموضوع:** %s' % (s.get('subject') or ''), '',
                '**Positive prompt**', '', '```', s['full_prompt'], '```', '', '**Negative prompt**', '', '```', s['full_negative'], '```', '']
    return '\n'.join(out)
