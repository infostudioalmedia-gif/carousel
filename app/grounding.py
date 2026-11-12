# -*- coding: utf-8 -*-
"""منع الهلوسة: (1) فحص جودة التفريغ قبل أي توليد  (2) تحقق آلي من كل شريحة مقابل التفريغ (كلمات/أرقام/مصطلحات لاتينية/اقتباس مصدر)."""
import re

AR_DIG = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
TASH = re.compile('[ً-ْـ]')
OTHER = re.compile('[Ѐ-ӿ฀-๿ಀ-೿぀-ヿ一-鿿가-힯ऀ-ॿ▀-▟֐-׿]')
ARAB = re.compile('[؀-ۿ]')
STOP = set('ده دي دول اللي في من علي عن او ولا لو ان انت انا هو هي ما مع كل قبل بعد بس كمان يعني طب هنا هناك كده كدا ايه ازاي'.split())
CTA_OK = None  # يتحسب بعد تعريف toks
NUMW = {'واحد': 1, 'احد': 1, 'اول': 1, 'تاني': 2, 'اتنين': 2, 'اثنين': 2, 'نوعين': 2, 'تلات': 3, 'تلاته': 3, 'ثلاث': 3, 'تالت': 3, 'اربع': 4, 'اربعه': 4,
        'رابع': 4, 'خمس': 5, 'خمسه': 5, 'خامس': 5, 'ست': 6, 'سته': 6, 'سادس': 6, 'سبع': 7, 'سبعه': 7, 'سابع': 7, 'تمان': 8, 'تمانيه': 8, 'ثمان': 8,
        'تسع': 9, 'تسعه': 9, 'عشر': 10, 'عشره': 10}


def norm(t):
    t = (t or '').translate(AR_DIG)
    t = TASH.sub('', t)
    t = re.sub('[أإآٱ]', 'ا', t).replace('ى', 'ي').replace('ة', 'ه')
    return re.sub(r'[^\w\s%.]', ' ', t.lower())


def toks(t):
    out = []
    for w in norm(t).split():
        w = w.strip('.')
        if w.startswith('ال') and len(w) > 3:
            w = w[2:]
        out.append(w)
    return out


def content_tokens(t):  # noqa
    return [w for w in toks(t) if len(w) >= 3 and w not in STOP and not re.fullmatch(r'[\d.%]+', w)]


CTA_OK = set(toks('اكتب التعليقات وهنرد عليك الخاص تواصل اكتبلنا سجل اهتمامك دلوقتي ابعت لنا الكومنتات وهنبلغك بالموعد رؤية'))


# ---------------------------------------------------------------- 1) جودة التفريغ
def quality(text, dur):
    words = (text or '').split()
    n = len(words)
    wpm = n / (dur / 60.0) if dur and dur > 0 else float(n)
    other = sum(1 for w in words if OTHER.search(w))
    arab = sum(1 for w in words if ARAB.search(w) and not OTHER.search(w))
    reasons = []
    if n < 25:
        reasons.append('الكلام قصير جدًا (%d كلمة)' % n)
    if dur and dur >= 20 and wpm < 35:
        reasons.append('كلام قليل جدًا بالنسبة لمدة الملف (%d كلمة في %d ثانية) — يا إما الملف من غير كلام أو التفريغ فشل' % (n, dur))
    if n and other / float(n) > 0.15:
        reasons.append('التفريغ فيه رموز ولغات غريبة (روسي/صيني/…) — علامة على فشل التفريغ')
    elif n and arab / float(n) < 0.4:
        reasons.append('أقل من نصف التفريغ عربي')
    return {'ok': not reasons, 'reasons': reasons, 'words': n, 'wpm': round(wpm, 1)}


def lines_from_text(text, dur):
    ws = (text or '').split()
    chunks = [ws[i:i + 9] for i in range(0, len(ws), 9)]
    step = (dur or 0) / max(1, len(chunks))
    return [{'t': round(i * step, 1), 's': ' '.join(c)} for i, c in enumerate(chunks)]


# ---------------------------------------------------------------- 2) تحقق من الشرايح
def _hd(hd):
    parts = []
    for ln in hd or []:
        for sg in (ln if isinstance(ln, list) else [ln]):
            parts.append(sg if isinstance(sg, str) else sg.get('t', ''))
    return parts


def slide_text(sl):
    parts = _hd(sl.get('hd')) + [sl.get('p', ''), str(sl.get('badge') or ''), ' '.join(sl.get('chips') or [])]
    s = sl.get('slider')
    if s:
        parts += [s.get('start', ''), s.get('end', '')]
    for r in sl.get('rows') or []:
        parts += [r.get('k', ''), r.get('v', ''), r.get('small', '')]
    return re.sub(r'\*\*', '', ' '.join(x for x in parts if x))


def cover_text(c):
    return ' '.join([c.get('a', ''), c.get('b', ''), c.get('c', '')] + list(c.get('strip') or []))


def cta_text(c):
    return ' '.join(_hd(c.get('hd')) + [re.sub(r'\*\*', '', c.get('p', '')), c.get('button', '')])


class Source:
    def __init__(self, transcript):
        self.vocab = set(content_tokens(transcript))
        self.pref = {v[:4] for v in self.vocab if len(v) >= 4}
        self.all = set(toks(transcript))
        self.nums = set(re.findall(r'\d+(?:\.\d+)?', norm(transcript)))
        for w in self.all:
            if w in NUMW:
                self.nums.add(str(NUMW[w]))
        self.latin = {w.lower() for w in re.findall(r'[A-Za-z]{2,}', transcript or '')}

    def has(self, t):
        return t in self.vocab or (len(t) >= 4 and t[:4] in self.pref)


def check(text, src, allow=frozenset(), min_ratio=0.30, quote=None):
    T = [t for t in content_tokens(text) if t not in allow]
    miss = [t for t in T if not src.has(t)]
    ratio = 1.0 if not T else (len(T) - len(miss)) / float(len(T))
    nums = [n for n in re.findall(r'\d+(?:\.\d+)?', norm(text)) if n not in src.nums]
    latin = [w for w in re.findall(r'[A-Za-z]{2,}', text or '') if w.lower() not in src.latin]
    reasons = []
    if ratio < min_ratio:
        reasons.append('كلمات مش في التفريغ: ' + '، '.join(miss[:5]))
    if nums:
        reasons.append('أرقام مش في التفريغ: ' + '، '.join(sorted(set(nums))))
    if latin:
        reasons.append('مصطلحات لاتينية مش في التفريغ: ' + '، '.join(sorted(set(latin))[:4]))
    if quote is not None:
        qt = content_tokens(quote)
        if not qt or sum(1 for t in qt if src.has(t)) / float(len(qt)) < 0.7:
            reasons.append('الاقتباس المرفق (src) مش موجود في التفريغ')
    return {'ok': not reasons, 'ratio': round(ratio, 2), 'reasons': reasons}


def verify(sb, transcript):
    """يرجّع تقرير تأصيل لكل شريحة (الغلاف، الكروت، CTA) مقابل التفريغ."""
    src = Source(transcript)
    rep = {'cover': check(cover_text(sb.get('cover', {})), src, quote=(sb.get('cover') or {}).get('src')),
           'slides': [check(slide_text(s), src, quote=s.get('src')) for s in sb.get('slides', [])],
           'cta': check(cta_text(sb.get('cta', {})), src, allow=CTA_OK, min_ratio=0.15, quote=(sb.get('cta') or {}).get('src'))}
    allr = [rep['cover']] + rep['slides'] + [rep['cta']]
    rep['bad'] = sum(1 for r in allr if not r['ok'])
    rep['total'] = len(allr)
    rep['summary'] = ('كل الشرايح مدعومة بالتفريغ' if not rep['bad'] else '%d من %d شرايح فيها كلام مش مدعوم بالتفريغ — راجعها' % (rep['bad'], rep['total']))
    return rep


# ---------------------------------------------------------------- 3) ثقة التفريغ (logprob من Scribe) — الإشارة اللي كانت بتتتجاهل
def scribe_quality(sc, dur, audio_db=None):
    """جودة التفريغ = فحص النص (رموز/لغات غريبة/قلة كلام) + ثقة Scribe نفسه لكل كلمة (logprob)."""
    text = (sc or {}).get('text', '') or ''
    ws = [w for w in (sc or {}).get('words', []) if w.get('type') == 'word']
    q = quality(text, dur)
    reasons = list(q['reasons'])
    lps = [w['logprob'] for w in ws if isinstance(w.get('logprob'), (int, float))]
    avg = (sum(lps) / len(lps)) if lps else None
    low = [w for w in ws if isinstance(w.get('logprob'), (int, float)) and w['logprob'] < -2.0]
    low_share = (len(low) / float(len(ws))) if ws else 1.0
    if avg is not None and avg < -1.0:
        reasons.append('ثقة خدمة التفريغ نفسها منخفضة جدًا (متوسط %.1f؛ السليم قريب من 0)' % avg)
    if ws and low_share > 0.25:
        reasons.append('%d%% من الكلمات خدمة التفريغ مش متأكدة منها' % round(low_share * 100))
    if audio_db is not None and audio_db > -40 and dur and dur >= 15 and q['wpm'] < 35 and not any('قليل' in r for r in reasons):
        reasons.append('الصوت مسموع (%.0f dB) لكن الكلمات المفرَّغة قليلة جدًا — غالبًا فشل في التفريغ' % audio_db)
    q.update({'ok': not reasons, 'reasons': reasons, 'avg_logprob': None if avg is None else round(avg, 2),
              'low_share': round(low_share, 2), 'low_words': [w['text'] for w in low][:15]})
    return q


# ---------------------------------------------------------------- 4) البنود الأساسية للكاروسيل (لو ناقص بند: توقف)
def _ok(x):
    return bool(x.strip()) if isinstance(x, str) else bool(x)


def validate_storyboard(sb, want_total=None):
    errs = []
    c = sb.get('cover') or {}
    for k, lab in (('a', 'عنوان الغلاف (a)'), ('b', 'سطر الغلاف (b)'), ('c', 'سطر الغلاف (c)')):
        if not _ok(c.get(k)):
            errs.append('الغلاف: %s ناقص' % lab)
    if not _ok((c.get('image') or {}).get('prompt')):
        errs.append('الغلاف: برومبت الصورة ناقص')
    sl = sb.get('slides') or []
    if len(sl) < 3:
        errs.append('عدد الكروت %d (لازم 3 على الأقل)' % len(sl))
    if want_total and len(sl) != want_total - 2:
        errs.append('عدد الشرايح %d بدل المطلوب %d' % (len(sl) + 2, want_total))
    for i, s in enumerate(sl, 2):
        tag = 'شريحة %d' % i
        if not any(t.strip() for t in _hd(s.get('hd'))):
            errs.append(tag + ': العنوان ناقص')
        if not (_ok(s.get('p')) or s.get('rows') or s.get('chips') or s.get('slider')):
            errs.append(tag + ': النص الأساسي ناقص')
        t = s.get('tab') or {}
        if not (_ok(t.get('ar')) and _ok(t.get('en'))):
            errs.append(tag + ': اسم التاب (عربي/إنجليزي) ناقص')
        if not _ok((s.get('image') or {}).get('prompt')):
            errs.append(tag + ': برومبت الصورة ناقص')
        if s.get('type') == 'table' and not s.get('rows'):
            errs.append(tag + ': جدول من غير صفوف')
    ct = sb.get('cta') or {}
    if not any(t.strip() for t in _hd(ct.get('hd'))):
        errs.append('صفحة CTA: العنوان ناقص')
    if not _ok(ct.get('p')):
        errs.append('صفحة CTA: النص ناقص')
    if not _ok(ct.get('button')):
        errs.append('صفحة CTA: نص الزر ناقص')
    if not _ok((ct.get('image') or {}).get('prompt')):
        errs.append('صفحة CTA: برومبت الصورة ناقص')
    if len((sb.get('caption') or '').strip()) < 30:
        errs.append('الكابشن ناقص')
    return errs
