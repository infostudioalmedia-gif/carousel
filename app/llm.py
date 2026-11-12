# -*- coding: utf-8 -*-
"""مزوّد توليد النص للـ storyboard: Gemini (مجاني) أو Claude API. الاختيار من config.json -> text_provider (auto | gemini | anthropic).
بدون أي مفتاح: generate() يرجّع None والخدمة تستنى كتابة النص يدويًا."""
import os, re, json, urllib.request, urllib.error
from pathlib import Path

CFG = json.loads((Path(__file__).parent / 'config.json').read_text(encoding='utf-8'))


def _key(env_var, file_key, patterns):
    k = os.environ.get(env_var)
    if k:
        return k.strip()
    f = CFG.get(file_key)
    if f and os.path.isfile(f):
        txt = open(f, encoding='utf-8-sig').read()
        for pat in patterns:
            m = re.search(pat, txt)
            if m:
                return m.group(1)
        parts = txt.strip().split()
        return parts[0] if parts else None
    return None



LAST = Path(__file__).parent / '.llm_status.json'


def _record(ok, model=None, err=None, secs=None):
    """آخر نتيجة توليد نص (لعرض حالة المزوّد الحقيقية في الصفحة)."""
    import time
    try:
        data = json.loads(LAST.read_text(encoding='utf-8')) if LAST.exists() else {}
    except (OSError, ValueError):
        data = {}
    now = int(time.time())
    if ok:
        data['ok_at'] = now; data['ok_model'] = model; data['ok_secs'] = secs
    else:
        data['fail_at'] = now; data['fail_err'] = (err or '')[:160]
    try:
        LAST.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def last_status():
    try:
        return json.loads(LAST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def anthropic_key():
    return _key(CFG.get('anthropic_env_var', 'ANTHROPIC_API_KEY'), 'anthropic_env_file', [r'(sk-ant-[A-Za-z0-9_-]+)', r'KEY\s*=\s*(\S+)'])


def gemini_key():
    return _key(CFG.get('gemini_env_var', 'GEMINI_API_KEY'), 'gemini_env_file', [r'(AIza[A-Za-z0-9_-]+)', r'KEY\s*=\s*(\S+)'])


def provider():
    """'gemini' | 'anthropic' | None"""
    p = (CFG.get('text_provider') or 'auto').lower()
    if p == 'gemini':
        return 'gemini' if gemini_key() else None
    if p == 'anthropic':
        return 'anthropic' if anthropic_key() else None
    if anthropic_key():
        return 'anthropic'
    if gemini_key():
        return 'gemini'
    return None


def _post(url, body, headers, timeout=300):
    h = dict(headers)
    h['content-type'] = 'application/json'
    req = urllib.request.Request(url, json.dumps(body).encode('utf-8'), h)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('HTTP %d: %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))
    except (TimeoutError, OSError) as e:                      # انتهى الوقت أو انقطع الاتصال
        raise RuntimeError('TIMEOUT: %s' % e)


def _gemini_models(key):
    req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200', headers={'x-goog-api-key': key})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('HTTP %d: %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))
    return [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]


STATE = Path(__file__).parent / '.llm_last_ok'


def _last_ok():
    try:
        return STATE.read_text(encoding='utf-8').strip() or None
    except OSError:
        return None


def _remember(model):
    try:
        STATE.write_text(model, encoding='utf-8')
    except OSError:
        pass


def gemini_model_order(key):
    """gemini_model في config.json (لو غير auto) وإلا نماذج Flash المتاحة من الأحدث للأقدم (المستقر أولًا)."""
    want = CFG.get('gemini_model', 'auto')
    if want and want != 'auto':
        return [want]
    names = _gemini_models(key)
    bad = ('image', 'tts', 'live', 'audio', 'embedding', 'robotics', 'computer', 'thinking', 'omni')
    flash = [n for n in names if 'flash' in n and not any(b in n for b in bad)]
    ver = lambda n: [int(x) for x in re.findall(r'\d+', n)][:3] or [0]
    stable = sorted([n for n in flash if not any(x in n for x in ('preview', 'exp', 'lite'))], key=ver, reverse=True)
    rest = sorted([n for n in flash if n not in stable], key=ver, reverse=True)
    order = stable + rest
    if not order:
        raise RuntimeError('لا يوجد نموذج Flash متاح لهذا المفتاح')
    last = _last_ok()
    if last in order:
        order.remove(last); order.insert(0, last)      # آخر نموذج نجح يتجرّب الأول
    return order[:6]


def pick_gemini_model(key):
    return gemini_model_order(key)[0]


RETRY_CODES = ('HTTP 429', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504')


def generate_gemini(prompt, budget=150):
    """يجرّب النماذج بالترتيب (من الأحدث للأخف) بمحاولتين لكل نموذج، وبحد أقصى `budget` ثانية إجمالًا،
    بعدها تتحوّل الخدمة للوضع اليدوي بدل ما تفضل مستنية."""
    import time
    t0 = time.time()
    key = gemini_key()
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 8192, 'responseMimeType': 'application/json'}}
    last = None
    for model in gemini_model_order(key):
        url = 'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model
        for attempt in range(2):
            if time.time() - t0 > budget:
                _record(False, err='مهلة %ds: %s' % (budget, last))
                raise RuntimeError('انتهت مهلة التوليد التلقائي (%ds). آخر خطأ: %s' % (budget, last))
            try:
                r = _post(url, body, {'x-goog-api-key': key}, timeout=45)
            except RuntimeError as e:
                last = '%s: %s' % (model, e)
                if str(e).startswith(RETRY_CODES) and attempt == 0:
                    time.sleep(3)
                    continue
                break                      # خطأ دائم أو انتهى الوقت أو ضغط متكرر -> النموذج اللي بعده
            cands = r.get('candidates') or []
            if not cands:
                last = '%s: رد فارغ %s' % (model, json.dumps(r.get('promptFeedback', r), ensure_ascii=False)[:150])
                break
            parts = cands[0].get('content', {}).get('parts', [])
            txt = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
            if txt.strip():
                _remember(model)
                _record(True, model, secs=int(time.time() - t0))
                return txt
            last = '%s: نص فارغ' % model
            break
    _record(False, err=str(last))
    raise RuntimeError('فشل توليد النص بكل النماذج المتاحة. آخر خطأ: %s' % last)


def generate_anthropic(prompt):
    r = _post('https://api.anthropic.com/v1/messages',
              {'model': CFG.get('anthropic_model', 'claude-sonnet-5-5'), 'max_tokens': 6000, 'messages': [{'role': 'user', 'content': prompt}]},
              {'x-api-key': anthropic_key(), 'anthropic-version': '2023-06-01'})
    return ''.join(c.get('text', '') for c in r.get('content', []))


def generate(prompt):
    p = provider()
    if p == 'gemini':
        return generate_gemini(prompt)
    if p == 'anthropic':
        return generate_anthropic(prompt)
    return None
