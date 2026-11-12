# -*- coding: utf-8 -*-
"""خط إنتاج «كاروسيل نوفمبر»: استلام → تفريغ → لقطات → storyboard → [توقف: برومبتات الصور] → تصميم وتقفيل."""
import os, re, json, time, uuid, shutil, subprocess, threading, traceback, zipfile, urllib.request, urllib.error
from pathlib import Path
import importlib, copy
import imgstyle
import grounding as G

APP = Path(__file__).parent
def _load_cfg():
    f = APP / 'config.json'
    if not f.exists(): f = APP / 'config.example.json'        # نسخة الريبو/السحابة من غير مسارات جهاز
    c = json.loads(f.read_text(encoding='utf-8'))
    for env, k, cast in (('ROOYA_CHROME', 'chrome', str), ('ROOYA_PORT', 'port', int), ('ROOYA_HOST', 'host', str), ('ROOYA_JOBS', 'jobs_dir', str)):
        if os.environ.get(env): c[k] = cast(os.environ[env])
    return c
CFG = _load_cfg()
JOBS = Path(CFG['jobs_dir']) if CFG.get('jobs_dir') else APP.parent / 'jobs'; JOBS.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp')

STYLES_DIR = APP / 'styles'
def list_styles():
    out = []
    for d in sorted(STYLES_DIR.iterdir(), reverse=True):
        m = d / 'manifest.json'
        if m.exists():
            mf = json.loads(m.read_text(encoding='utf-8')); out.append({k: mf.get(k) for k in ('id', 'label', 'title', 'month', 'desc')})
    return sorted(out, key=lambda x: x['month'], reverse=True)   # الأحدث أولًا (الافتراضي)
def style_mf(sid):
    return json.loads((STYLES_DIR / sid / 'manifest.json').read_text(encoding='utf-8'))
def renderer_for(sid):
    return importlib.import_module(style_mf(sid)['renderer'])

# ------------------------------------------------------------------ حالة الكاروسيل
def jdir(jid): return JOBS / jid
def load(jid):
    p = jdir(jid) / 'job.json'; last = None
    for _ in range(8):                      # ويندوز: ملف ممكن يتقفل لحظات (قراءة متزامنة/أنتي فيرس)
        try: return json.loads(p.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as ex: last = ex; time.sleep(0.15)
    raise last
def save(job):
    with LOCK:
        p = jdir(job['id']) / 'job.json'
        tmp = p.with_name('job.%s.tmp' % uuid.uuid4().hex[:6]); data = json.dumps(job, ensure_ascii=False, indent=1)
        tmp.write_text(data, encoding='utf-8'); last = None
        try:
            for _ in range(12):             # WinError 5 (Access denied) عابر لو حد ماسك job.json لحظتها
                try: os.replace(tmp, p); return
                except OSError as ex: last = ex; time.sleep(0.2)
            try: p.write_text(data, encoding='utf-8'); return     # آخر حل: كتابة مباشرة
            except OSError: raise last
        finally:
            try: tmp.unlink()
            except OSError: pass
def logj(job, msg):
    job.setdefault('log', []).append('%s  %s' % (time.strftime('%H:%M:%S'), msg)); save(job)
def new_job(name, style=None, slides_total=None):
    jid = time.strftime('%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4]
    (jdir(jid) / 'images').mkdir(parents=True); (jdir(jid) / 'frames').mkdir()
    job = {'id': jid, 'name': name or jid, 'status': 'received', 'log': [], 'created': time.time(), 'choices': {}, 'folder': '', 'out': '', 'style': style or list_styles()[0]['id'], 'slides_total': slides_total}
    save(job); return job

def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout or b'').decode('utf-8', 'replace'), (r.stderr or b'').decode('utf-8', 'replace')


# ------------------------------------------------------------------ تقدّم الشغل (خطة مراحل بتقديرات زمن)
def plan(job, steps, kind='analyze'):
    """steps: [(label, est_seconds)] — العميل يحسب النسبة والوقت المتبقي من الخطة."""
    job['plan'] = [{'label': l, 'est': e} for l, e in steps]; job['kind'] = kind; job['stage'] = 0; job['stage_t0'] = time.time(); job.pop('dl_pct', None); save(job)
def stage(job, i, est=None):
    job['stage'] = i; job['stage_t0'] = time.time(); job.pop('dl_pct', None)
    if est is not None and i < len(job.get('plan', [])): job['plan'][i]['est'] = max(1, est)
    save(job)
def end_plan(job):
    job['last_stage'] = job.get('stage', 0); job.pop('plan', None); job.pop('stage', None); job.pop('dl_pct', None)

def clean_path(p):
    return (p or '').strip().strip('"').strip("'").strip()
def is_local_file(p):
    p = clean_path(p)
    return bool(p) and os.path.isfile(p)

def render_est(job):
    try: return style_mf(job.get('style', 'november')).get('render_est', 40)
    except Exception: return 40

def recover():
    """عند تشغيل السيرفر: أي كاروسيل كان شغّال وانقطع يتعلّم فاشل (مع إمكانية إعادة المحاولة)."""
    for d in JOBS.iterdir():
        if (d / 'job.json').exists():
            j = load(d.name)
            if j.get('status') in ('received', 'analyzing', 'rendering'):
                j['status'] = 'failed'; j['error'] = 'انقطعت العملية (إعادة تشغيل السيرفر) — اضغط إعادة المحاولة'; end_plan(j); save(j)

# ------------------------------------------------------------------ فولدر المشروع (جنب المصدر) + الانسرتات بأسماء الشرايح
SUBDIRS = {'inserts': 'الانسرتات', 'slides': 'الشرايح', 'files': 'ملفات'}
MARK = '.rooya-job'

def safe_name(s, default='project'):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', ' ', str(s or '')).strip(' .')
    return (re.sub(r'\s+', ' ', s) or default)[:80]

def default_base(job):
    inp = job.get('input') or {}
    if inp.get('type') == 'path' and inp.get('path'):
        return Path(clean_path(inp['path'])).parent                       # نفس مكان المصدر
    return Path(CFG.get('default_out_dir') or (Path.home() / 'Downloads' / 'Rooya Carousels'))

def _owned(p, jid):
    m = p / MARK
    if m.exists():
        try: return m.read_text(encoding='utf-8').strip() == jid
        except OSError: return False
    return not any(p.iterdir()) if p.exists() else True

def init_project(job, base=None):
    """يحدد فولدر المشروع (جنب المصدر افتراضيًا) ويعمل الفولدرات الفرعية جنب بعض، ويتأكد إنه قابل للكتابة. بيرجّع المسار."""
    jid = job['id']; base = Path(base) if base else (Path(job['out']) if job.get('out') else default_base(job))
    name = safe_name(job.get('name') or jid, jid); cand = base / name; n = 1
    while cand.exists() and not _owned(cand, jid):
        n += 1; cand = base / ('%s (%d)' % (name, n))
    try:
        for sub in SUBDIRS.values(): (cand / sub).mkdir(parents=True, exist_ok=True)
        (cand / MARK).write_text(jid, encoding='utf-8')
        t = cand / '.write-test'; t.write_text('ok'); t.unlink()
    except OSError as ex:
        logj(job, '⚠ تعذّر الكتابة في %s (%s) — هستخدم فولدر داخلي' % (cand, ex))
        cand = jdir(jid) / 'project'
        for sub in SUBDIRS.values(): (cand / sub).mkdir(parents=True, exist_ok=True)
    job['project_dir'] = str(cand); job['project_base'] = str(cand.parent)
    return cand

def migrate_legacy(job):
    """صور اتحفظت قبل كده جوه فولدر الكاروسيل الداخلي (images/sN.jpg) تتنقل لفولدر الانسرتات بأسماء الشرايح."""
    imgs = jdir(job['id']) / 'images'
    if not (imgs.is_dir() and job.get('slots')): return
    for f in list(imgs.glob('s*.*')):
        if f.suffix.lower() in IMG_EXT and re.match(r'^s\d+$', f.stem) and any(s['id'] == f.stem for s in job['slots']):
            try: save_insert(job, f.stem, f, f.suffix)
            except Exception: pass

def project_dir(job):
    if not job.get('project_dir') or not Path(job['project_dir']).exists():
        init_project(job); migrate_legacy(job); save(job)
    return Path(job['project_dir'])

def move_project(job, new_base):
    """تغيير مكان المشروع: بيعمل الفولدرات في المكان الجديد وينسخ اللي فيها (القديم بيفضل كما هو)."""
    old = Path(job['project_dir']) if job.get('project_dir') else None
    new = init_project(job, new_base); job['out'] = str(new_base)
    if old and old.exists() and old.resolve() != new.resolve():
        shutil.copytree(old, new, dirs_exist_ok=True); logj(job, '📁 اتنقل المشروع إلى: %s (النسخة القديمة لسه موجودة في: %s)' % (new, old))
    return new

def slide_no(sid): return int(str(sid)[1:]) + 1

def slot_title(job, sid):
    for s in job.get('slots') or []:
        if s['id'] == sid: return safe_name(str(s.get('label', '')).split('—')[-1].strip(), 'slide')
    return 'slide'

def inserts_dir(job): return project_dir(job) / SUBDIRS['inserts']

def find_insert(job, sid):
    """أحدث صورة باسم الشريحة (slide-03 ...) في فولدر الانسرتات، أو أقدم صورة مرفوعة داخل فولدر الكاروسيل الداخلي."""
    d = (Path(job['project_dir']) / SUBDIRS['inserts']) if job.get('project_dir') else None; pre = 'slide-%02d' % slide_no(sid)
    hits = [p for p in d.iterdir() if p.suffix.lower() in IMG_EXT and (p.stem == pre or p.stem.startswith(pre + '_') or p.stem.startswith(pre + ' '))] if (d and d.exists()) else []
    if hits: return max(hits, key=lambda p: p.stat().st_mtime)
    return next((p for p in (jdir(job['id']) / 'images').glob(sid + '.*') if p.suffix.lower() in IMG_EXT), None)

def save_insert(job, sid, src, ext=None):
    """يحفظ صورة الخانة في فولدر الانسرتات باسم الشريحة (slide-03_التسخين.jpg) ويشيل أي نسخة قديمة لنفس الشريحة."""
    d = inserts_dir(job); pre = 'slide-%02d' % slide_no(sid); ext = (ext or Path(src).suffix).lower()
    dst = d / ('%s_%s%s' % (pre, slot_title(job, sid), ext))
    tmp = d / ('.tmp-%s%s' % (uuid.uuid4().hex[:6], ext))
    if str(src) != str(dst): shutil.copyfile(src, tmp) if not isinstance(src, bytes) else tmp.write_bytes(src)
    else: return dst
    for old in d.iterdir():
        if old.suffix.lower() in IMG_EXT and (old.stem == pre or old.stem.startswith(pre + '_') or old.stem.startswith(pre + ' ')): old.unlink()
    for _ in range(8):
        try: os.replace(tmp, dst); break
        except OSError: time.sleep(0.3)
    for old in (jdir(job['id']) / 'images').glob(sid + '.*'):
        try: old.unlink()
        except OSError: pass
    return dst

# ------------------------------------------------------------------ مرحلة 1: التحليل
def read_key(path):
    txt = open(path, encoding='utf-8-sig').read()
    m = re.search(r'(?:API_KEY|XI_API_KEY)\s*=\s*["\']?([^\s"\']+)', txt) or re.search(r'(sk_[A-Za-z0-9_]+)', txt)
    return m.group(1) if m else txt.strip().split()[0]

def scribe(audio, key, lang):
    import uuid as _u
    b = _u.uuid4().hex; data = open(audio, 'rb').read(); parts = []
    fields = [('model_id', 'scribe_v1'), ('timestamps_granularity', 'word')] + ([('language_code', lang)] if lang else [])
    for k, v in fields: parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="a.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n' % b).encode() + data + b'\r\n')
    parts.append(('--%s--\r\n' % b).encode())
    req = urllib.request.Request('https://api.elevenlabs.io/v1/speech-to-text', b''.join(parts),
                                 {'xi-api-key': key, 'Content-Type': 'multipart/form-data; boundary=' + b})
    return json.loads(urllib.request.urlopen(req, timeout=900).read().decode('utf-8'))

def mmss(t): return '%02d:%02d' % (int(t) // 60, int(t) % 60)

def transcript_lines(sc, n=9):
    words = [w for w in sc.get('words', []) if w.get('type') == 'word']; out = []
    for i in range(0, len(words), n):
        ch = words[i:i + n]; out.append({'t': round(ch[0]['start'], 1), 's': ' '.join(w['text'] for w in ch)})
    return out

STORYBOARD_SPEC = '''أنت مصمّم محتوى لشركة «رؤية لحلول صناعة الألبان». حوّل التفريغ التالي إلى كاروسيل بنمط «كاروسيل نوفمبر».
القواعد:
- **قاعدة التأصيل (إلزامية):** استخدم فقط المعلومات الموجودة نصًّا في التفريغ. ممنوع تضيف أي معلومة أو رقم أو اسم أو ادعاء أو خدمة أو ميزة من خارج التفريغ، وممنوع تعمل كاروسيل تعريفي أو دعائي عن الشركة من عندك. كل شريحة لازم يكون ليها "src": اقتباس حرفي قصير (حتى 12 كلمة) من التفريغ يدعمها.
- لو التفريغ قصير أو مشوّش أو مش كافي لعمل كاروسيل، **ماتكتبش كاروسيل**؛ رجّع بس: {"error": "insufficient_source", "reason": "السبب"}.
- لهجة مصرية بسيطة (إعادة صياغة من التفريغ بس). لا تخترع أرقامًا أو مواعيد أو أماكن. أي معلومة غير مؤكدة (موعد، مكان، سعر) تدخل في "needs_confirmation".
- غلاف + كروت في "slides" (الافتراضي 4 إلى 5، ويُلتزم بالعدد المطلوب لو اتحدد) بدون CTA + صفحة CTA ثابتة في "cta" (حتمية، من محتوى الملف) — الباركود يتركّب تلقائيًا.
- الغلاف: تسلسل قراءة من الأكبر للأصغر: a (الكلمة الأقوى، قصيرة) ثم b (جملة أقصر من 20 حرفًا) ثم c. "accent" كلمة/رقم داخل b يتلون.
- عناوين الكروت سطران كحد أقصى، كل سطر 3–4 كلمات. النص p لا يزيد عن 3 أسطر (حوالي 110 حرفًا). **نص** = كلمات بخط ثقيل.
- كل شريحة لها "tab": {"ar": كلمة واحدة, "en": كلمة إنجليزية}.
- لكل شريحة صورة: "image": {"prompt": ..., "scene_ar": ..., "at": ...}.
  • **prompt** = وصف إنجليزي **مفصّل وطويل (من 70 إلى 120 كلمة)** للمشهد اللي المتحدث بيشرحه في الجزء ده من الفيديو بالظبط، يشمل: المرحلة أو العملية (إيه اللي بيحصل فيها وبعدها إيه)، المعدة أو المادة بأجزائها وتفاصيلها المذكورة في الكلام (الخامة، العدد، الشكل، مكانها)، الحركة أو الإجراء الجاري، موضع الكاميرا وزاوية اللقطة وقربها، وتفاصيل البيئة المحيطة. اكتبه كأنك بتوصف لمصوّر مشهد واحد محدد من الفيديو. **ممنوع** تضيف معدات أو أرقام أو معلومات مش موجودة في التفريغ، و**ماتذكرش الأسلوب ولا الإضاءة ولا الألوان** لأن نمط رؤية بيتضاف تلقائيًا (واقعي، ألوان طبيعية، بدون نصوص أو وجوه).
  • **scene_ar** = سطر أو سطرين بالعربي: أنهي مرحلة/جزء من الفيديو الصورة دي بتمثله وإيه الكلام اللي بتعبّر عنه.
  • **at** = ثانية في التفريغ ذات صلة (لو مفيش فيديو اتركها null).
- ممنوع روابط على الشرايح.
أخرج JSON فقط بهذا الشكل:
{
 "title": "اسم قصير للكاروسيل",
 "cover": {"a": "...", "b": "...", "accent": "...", "c": "...", "strip": ["...","...","..."], "sticker": "calc|cal|none", "src": "اقتباس حرفي من التفريغ", "image": {"prompt": "وصف مفصّل 70-120 كلمة...", "scene_ar": "...", "at": 5}},
 "slides": [
  {"type": "photo", "tab": {"ar": "السبب", "en": "Cause"}, "hd": [[{"t":"سطر 1","c":"hl"}],[{"t":"سطر 2","c":"hl rd"}]],
   "src": "اقتباس حرفي من التفريغ", "p": "نص مع **تأكيد**", "badge": "90%", "chips": ["..."], "slider": {"start": "...", "end": "..."}, "sticker": "cal", "button": "...",
   "image": {"prompt": "...", "scene_ar": "...", "at": 12}},
  {"type": "table", "tab": {...}, "src": "اقتباس حرفي", "hd": [[{"t":"...","c":"hl"}]], "rows": [{"k":"...","v":"...","small":"..."}], "image": {...}}
 ],
 "cta": {"tab": {"ar": "تواصل", "en": "Contact"}, "hd": [[{"t":"سطر","c":"hl"}],[{"t":"سطر","c":"hl rd"}]], "p": "دعوة للإجراء من محتوى الملف + اكتب **«كلمة»** في التعليقات — وهنرد عليك على الخاص", "button": "نص الزر", "sticker": "cal|none", "src": "اقتباس حرفي", "image": {"prompt": "...", "at": 50}},
 "caption": "كابشن البوست بالمصري مع هاشتاجات",
 "needs_confirmation": ["..."]
}
(chips_icon: "x" لو الشيبس نفي (مش كذا)، وإلا علامة صح.) (c: "hl" هايلايت تيل · "hl rd" هايلايت أحمر للمشكلة · "" بدون. الحقول badge/chips/slider/sticker/button اختيارية.)
'''

def storyboard_request(job):
    mf = style_mf(job.get('style', 'november'))
    hint = 'النمط المختار: «%s» — %s\nالحقول المناسبة للنمط: %s\n(أضف points: [نقاط قصيرة] للشرايح لو النمط أكتوبر.)\n\n' % (mf['label'], mf['desc'], mf['fields'])
    n = job.get('slides_total')
    cnt = ('عدد الشرايح الإجمالي المطلوب: %d بالظبط = غلاف + %d كروت داخل "slides" + صفحة CTA في "cta".' % (n, n - 2) + '\n') if n else 'عدد الشرايح: اختار الأنسب (من 5 إلى 7 إجمالًا).'+'\n'
    hint += cnt + '\n'
    tr = '\n'.join((l['s'] if job.get('text_only') else '[%s] %s' % (mmss(l['t']), l['s'])) for l in job['transcript_lines'])
    return STORYBOARD_SPEC + '\n' + hint + '---\nالتفريغ:\n' + tr + '\n'

import llm

def call_claude(prompt):
    """يولّد نص الـ storyboard عبر المزوّد المتاح (Gemini / Claude API)، أو None لو مفيش مفتاح."""
    return llm.generate(prompt)

def extract_json(txt):
    i = txt.index('{'); depth = 0
    for j in range(i, len(txt)):
        depth += txt[j] == '{'; depth -= txt[j] == '}'
        if depth == 0: return json.loads(txt[i:j + 1])
    raise ValueError('JSON غير مكتمل')

def safe_copy(src, dst, tries=3):
    """ينسخ الملف ويتأكد إن الحجم متطابق (نسخة ناقصة = قراءة فاشلة بعدين)."""
    for n in range(tries):
        shutil.copyfile(src, dst)
        if os.path.getsize(dst) == os.path.getsize(src):
            return
        time.sleep(2)
    raise RuntimeError('نسخ الملف ما اكتملش (الحجم مختلف عن الأصل): %s' % src)

def probe_media(inp, tries=6, log=None):
    """يقرا مدة الملف وأنواع المسارات. لو فشل (ملف لسه مقفول من الأنتي-فيروس/تالف) يعيد المحاولة، وبعدها يوقف برسالة واضحة."""
    last = ''
    for n in range(tries):
        rc, o, e = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(inp)])
        try:
            data = json.loads(o or '{}')
            dur = float((data.get('format') or {}).get('duration') or 0)
            types = [s.get('codec_type') for s in data.get('streams', [])]
        except (ValueError, TypeError):
            dur, types = 0.0, []
        if dur > 0 and types:
            return dur, types
        last = (e or o or '').strip()[-220:]
        if log: log('⚠ قراءة الملف فشلت (محاولة %d/%d): %s' % (n + 1, tries, last or 'نتيجة فاضية'))
        time.sleep(2)
    raise RuntimeError('تعذّر قراءة الملف بعد %d محاولات (ممكن يكون مقفول من برنامج تاني أو تالف): %s' % (tries, last or 'ffprobe رجّع نتيجة فاضية'))

def extract_audio(inp, out, tries=4, extra=None):
    """يستخرج الصوت ويتأكد إن الملف اتعمل فعلًا (مش بس إن الأمر اتنفّذ)."""
    err = ''
    for n in range(tries):
        rc, o, e = run(['ffmpeg', '-y', '-i', str(inp), '-vn'] + (extra or ['-ac', '1', '-ar', '16000', '-b:a', '48k']) + [str(out)])
        err = (e or '')[-220:]
        if Path(out).exists() and Path(out).stat().st_size > 2000:
            return
        time.sleep(2)
    raise RuntimeError('تعذّر استخراج الصوت من الملف: %s' % (err.strip() or 'مفيش ناتج'))


def audio_level(path):
    rc, o, e = run(['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'volumedetect', '-f', 'null', '-'])
    m = re.search(r'mean_volume:\s*(-?[\d.]+) dB', e)
    return float(m.group(1)) if m else None

def transcribe_checked(job, d):
    """يفرّغ الصوت ويتحقق (نص + ثقة Scribe). لو مشكوك فيه: 3 محاولات (الثالثة بصوت عالي الجودة)، وإلا يرجّع جودة فاشلة."""
    key = os.environ.get('ELEVENLABS_API_KEY', '').strip() or read_key(CFG['eleven_env']); dur = job.get('duration', 0)
    job['audio_db'] = audio_level(d / 'audio.mp3'); save(job)
    sc = None; q = {'ok': False, 'reasons': ['لم تتم أي محاولة'], 'words': 0}
    for n in range(3):
        if n == 2:
            try: extract_audio(d / job['input']['file'], d / 'audio_hq.wav', tries=2, extra=['-ac', '1', '-ar', '44100'])
            except Exception as ex: logj(job, 'تعذّر تجهيز نسخة عالية الجودة: %s' % ex)
            path = d / 'audio_hq.wav'
        else:
            path = d / 'audio.mp3'
        if n == 2 and not (Path(path).exists() and Path(path).stat().st_size > 2000):
            logj(job, 'تعذّر تجهيز نسخة عالية الجودة من الصوت — هنكمّل بالنتيجة الحالية')
            break
        if not Path(path).exists():
            raise RuntimeError('ملف الصوت المحلي مش موجود: %s' % path)
        try:
            sc = scribe(str(path), key, CFG.get('language'))
        except Exception as ex:
            logj(job, 'فشل استدعاء التفريغ (محاولة %d/3): %s' % (n + 1, ex))
            sc = None; q = {'ok': False, 'reasons': ['تعذّر الاتصال بخدمة التفريغ: %s' % str(ex)[:120]], 'words': 0}
            time.sleep(3); continue
        q = G.scribe_quality(sc, dur, job.get('audio_db'))
        job['transcript_attempts'] = n + 1
        if q['ok']:
            return sc, q
        logj(job, '⚠ تفريغ مشكوك فيه (محاولة %d/3): %s' % (n + 1, ' | '.join(q['reasons'])))
        time.sleep(2)
    return sc, q

def reset_job(jid):
    """إعادة التشغيل من البداية: يمسح ناتج التحليل ويحتفظ بالإدخال والاسم والنمط."""
    job = load(jid); d = jdir(jid)
    for name in ('audio.mp3', 'audio_hq.wav', 'scribe.json', 'storyboard_request.md'):
        (d / name).unlink(missing_ok=True)
    f = d / 'storyboard.json'
    if f.exists(): f.replace(d / 'storyboard.rejected.json')
    for dn in ('frames', 'out_draft', 'out', 'images_auto'):
        shutil.rmtree(d / dn, ignore_errors=True)
    (d / 'frames').mkdir(exist_ok=True)
    keep = {k: job[k] for k in ('id', 'name', 'created', 'style', 'input', 'folder', 'out') if k in job}
    keep.update({'status': 'received', 'choices': {}, 'slides_total': None,
                 'log': (job.get('log') or [])[-3:] + ['%s  ↻ إعادة التشغيل من البداية' % time.strftime('%H:%M:%S')]})
    job.clear(); job.update(keep); save(job)


STAGE_NAMES = ['استلام', 'تجهيز الصوت', 'لقطات الفيديو', 'تفريغ الكلام', 'عدد الشرايح', 'كتابة نص الشرايح', 'التصميم المبدئي', 'الانسرتات', 'التصميم النهائي', 'التسليم']

def goto_stage(jid, i):
    """الرجوع لمرحلة في خريطة التنفيذ والبدء منها: 0-3 من الأول، 4 عدد الشرايح، 5 كتابة النص، 6 التصميم المبدئي، 7 الانسرتات، 8-9 التصميم النهائي.
    يرمي ValueError برسالة واضحة لو المرحلة مش متاحة. كل مرحلة بتمسح ناتجها بس، وصور الانسرتات المحفوظة في فولدر المشروع بتفضل."""
    job = load(jid); d = jdir(jid); i = int(i)
    if not 0 <= i <= 9: raise ValueError('مرحلة غير صحيحة')
    if job.get('status') in ('received', 'analyzing', 'rendering'): raise ValueError('الكاروسيل شغّال دلوقتي — استنى لما يخلص')
    if i <= 3:
        reset_job(jid); start(analyze, jid); return STAGE_NAMES[i]
    if not (job.get('transcript') or '').strip(): raise ValueError('مفيش تفريغ لسه — ابدأ من «تفريغ الكلام»')
    sbf = d / 'storyboard.json'
    if i == 4:
        if sbf.exists(): sbf.replace(d / 'storyboard.rejected.json')
        for k in ('slides_total', 'slides_confirmed', 'slots', 'storyboard', 'grounding', 'validation_errors', 'results', 'draft', 'error'): job.pop(k, None)
        job['choices'] = {}; job['slides_suggest'] = suggest_slides(job); job['status'] = 'awaiting_slides'
        logj(job, '↩ رجعت لمرحلة اختيار عدد الشرايح'); save(job); return STAGE_NAMES[i]
    if i == 5:
        if not job.get('slides_total'): raise ValueError('اختار عدد الشرايح الأول')
        if sbf.exists(): sbf.replace(d / 'storyboard.rejected.json')
        for k in ('slots', 'storyboard', 'grounding', 'validation_errors', 'results', 'draft', 'error'): job.pop(k, None)
        job['slides_confirmed'] = True; job['status'] = 'analyzing'; logj(job, '↩ إعادة كتابة نص الشرايح'); save(job); start(storyboard_stage, jid); return STAGE_NAMES[i]
    if i == 6:
        if not sbf.exists(): raise ValueError('مفيش نص شرايح لسه — ابدأ من «كتابة نص الشرايح»')
        for k in ('results', 'error', 'validation_errors'): job.pop(k, None)
        job['status'] = 'analyzing'; logj(job, '↩ إعادة التجهيز والتصميم المبدئي'); save(job); start(prepare, jid); return STAGE_NAMES[i]
    if not job.get('slots') or not sbf.exists(): raise ValueError('جهّز التصميم المبدئي الأول')
    if i == 7:
        job['status'] = 'awaiting_images'; job.pop('error', None); logj(job, '↩ رجعت لمرحلة الانسرتات'); save(job); return STAGE_NAMES[i]
    job['status'] = 'rendering'; job.pop('error', None); logj(job, '↩ إعادة التصميم النهائي'); save(job); start(finish, jid); return STAGE_NAMES[i]

TEXT_EXT = ('.txt', '.md', '.srt', '.docx')

def read_text_file(path):
    """يقرا ملف نصي (txt / md / srt / docx) ويرجّع النص. يرمي ValueError لو فاضي أو غير مقروء."""
    path = Path(path); ext = path.suffix.lower(); raw = path.read_bytes()
    if ext == '.docx':
        import zipfile, io, xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z: root = ET.fromstring(z.read('word/document.xml'))
        except Exception: raise ValueError('ملف Word مش مقروء — احفظه تاني كـ docx أو txt')
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        paras = [''.join(t.text or '' for t in p.iter(ns + 't')) for p in root.iter(ns + 'p')]
        text = '\n'.join(x for x in paras if x.strip())
    else:
        text = None
        for enc in ('utf-8-sig', 'utf-16', 'cp1256'):
            try: text = raw.decode(enc); break
            except Exception: continue
        if text is None: raise ValueError('مش قادر أقرا ترميز الملف — احفظه UTF-8')
        if ext == '.srt':
            text = '\n'.join(l for l in text.splitlines() if l.strip() and not l.strip().isdigit() and '-->' not in l)
    text = re.sub(r'[ \t]+', ' ', text).strip()
    if len(text.split()) < 25: raise ValueError('النص قصير (أقل من 25 كلمة) — مش كفاية لعمل كاروسيل')
    return text

def analyze_text(jid):
    """مدخل نصي (بدون صوت): نقرا الملف ونعتمده كتفريغ ونروح لاختيار عدد الشرايح."""
    job = load(jid); d = jdir(jid)
    try:
        job['status'] = 'analyzing'; save(job)
        pdir = init_project(job); logj(job, '📁 فولدر المشروع: %s' % pdir)
        plan(job, [('استلام الملف', 2), ('قراءة النص', 2)])
        inp = next((p for p in d.glob('input.*')), None)
        if not inp: raise RuntimeError('لا يوجد ملف إدخال')
        job['input']['file'] = inp.name; stage(job, 1)
        text = read_text_file(inp)
        job.update({'transcript': text, 'transcript_lines': G.lines_from_text(text, 0), 'source_text': True, 'text_only': True, 'has_video': False, 'duration': 0,
                    'transcript_quality': {'ok': True, 'reasons': [], 'words': len(text.split()), 'user': True}})
        logj(job, 'النوع: ملف نصي · %d كلمة' % len(text.split())); end_plan(job)
        if job.get('slides_total') or job.get('slides_confirmed'):
            save(job); storyboard_stage(jid); return
        job['slides_suggest'] = suggest_slides(job); job['status'] = 'awaiting_slides'
        logj(job, '✋ توقف: اقتراح عدد الشرايح (%d) جاهز — اختار العدد وكمّل' % job['slides_suggest']['n'])
        save(job)
    except Exception as ex:
        job = load(jid); end_plan(job); job['status'] = 'failed'; job['error'] = str(ex); logj(job, 'فشل: %s' % ex); traceback.print_exc()

def analyze(jid):
    job = load(jid); d = jdir(jid)
    if os.path.splitext((job.get('input') or {}).get('name', '') or '')[1].lower() in TEXT_EXT: return analyze_text(jid)
    try:
        job['status'] = 'analyzing'; save(job)
        src = job.get('input', {})
        pdir = init_project(job); logj(job, '📁 فولدر المشروع: %s' % pdir)
        # 1) الاستلام
        plan(job, [('استلام الملف', 90 if src.get('type') == 'url' else 4), ('تجهيز الصوت', 6), ('استخراج اللقطات', 25),
                   ('تفريغ الكلام (Scribe)', 30)])
        if src.get('type') == 'path':
            lp = clean_path(src['path']); logj(job, 'نسخ الملف من الجهاز…')
            safe_copy(lp, d / ('input' + (os.path.splitext(lp)[1].lower() or '.bin')))
        elif src.get('type') == 'url':
            logj(job, 'تحميل الرابط…')
            pr = subprocess.Popen(['yt-dlp', '--newline', '--no-update', '-f', 'bv*[height<=720]+ba/b[height<=720]/b', '--merge-output-format', 'mp4',
                                   '-o', str(d / 'input.%(ext)s'), src['url']], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            tail = []; last = 0
            for raw in pr.stdout:
                line = raw.decode('utf-8', 'replace'); tail = (tail + [line])[-6:]
                m = re.search(r'(\d+(?:\.\d+)?)%', line)
                if m and time.time() - last > 1.2:
                    job['dl_pct'] = float(m.group(1)); save(job); last = time.time()
            if pr.wait() != 0: raise RuntimeError('تعذّر تحميل الرابط: ' + ' '.join(tail)[-300:])
        inp = next((p for p in d.glob('input.*')), None)
        if not inp: raise RuntimeError('لا يوجد ملف إدخال')
        job['input']['file'] = inp.name; stage(job, 1)
        # 2) فحص الملف (مع إعادة محاولة) — لو مش قابل للقراءة نوقف برسالة واضحة بدل ما نكمل على مدة صفر
        dur, types = probe_media(inp, log=lambda m: logj(job, m))
        if 'audio' not in types:
            raise RuntimeError('الملف مفيهوش مسار صوت خالص — مفيش كلام يتفرّغ منه. ارفع ملف فيه صوت.')
        job['duration'] = dur
        job['has_video'] = ('video' in types) and inp.suffix.lower() not in ('.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac')
        logj(job, 'النوع: %s · المدة %s' % ('فيديو' if job['has_video'] else 'صوت', mmss(job['duration'])))
        # 3) صوت للتفريغ (مع تحقق إن الملف اتعمل فعلًا)
        extract_audio(inp, d / 'audio.mp3')
        stage(job, 2, 25 if job['has_video'] else 1)
        # 4) لقطات المشاهد (فيديو)
        if job['has_video']:
            logj(job, 'استخراج لقطات المشاهد…')
            run(['ffmpeg', '-y', '-i', str(inp), '-vf', "select='gt(scene,0.30)',scale=960:-2", '-vsync', 'vfr', '-frames:v', '30',
                 str(d / 'frames' / 'scene_%03d.jpg')])
            if len(list((d / 'frames').glob('scene_*.jpg'))) < 6:
                step = max(1, job['duration'] / 12)
                run(['ffmpeg', '-y', '-i', str(inp), '-vf', 'fps=1/%.2f,scale=960:-2' % step, '-frames:v', '14', str(d / 'frames' / 'scene_%03d.jpg')])
        stage(job, 3, job.get('duration', 60) * 0.22 + 10)
        # 5) تفريغ مع بوابة جودة (شرط أساسي: لو مش متأكد يقف)
        logj(job, 'تفريغ الكلام (ElevenLabs Scribe)…')
        sc, q = transcribe_checked(job, d)
        if sc:
            (d / 'scribe.json').write_text(json.dumps(sc, ensure_ascii=False), encoding='utf-8')
            job['transcript'] = sc.get('text', ''); job['transcript_lines'] = transcript_lines(sc)
        job['transcript_quality'] = q; save(job)
        if not q['ok'] and not job.get('source_text'):
            end_plan(job); job['status'] = 'needs_text'
            logj(job, '⛔ مش متأكد من تفريغ الصوت (بعد %s محاولات) — توقفت. أعد التشغيل من البداية. السبب: %s' % (job.get('transcript_attempts', 3), ' | '.join(q['reasons'])))
            return
        end_plan(job)
        if (d / 'storyboard.json').exists() or job.get('slides_total') or job.get('slides_confirmed'):
            storyboard_stage(jid); return           # العدد محدد مسبقًا أو النص جاهز -> كمّل من غير توقف
        job['slides_suggest'] = suggest_slides(job)
        job['status'] = 'awaiting_slides'
        logj(job, '✋ توقف: اقتراح عدد الشرايح (%d) جاهز — اختار العدد وكمّل' % job['slides_suggest']['n'])
    except Exception as ex:
        job = load(jid); end_plan(job); job['status'] = 'failed'; job['error'] = str(ex); logj(job, 'فشل: %s' % ex); traceback.print_exc()

ORD = {'اول': 1, 'أول': 1, 'الاول': 1, 'الأول': 1, 'تاني': 2, 'التاني': 2, 'ثاني': 2, 'الثاني': 2, 'تالت': 3, 'التالت': 3, 'ثالث': 3, 'الثالث': 3,
       'رابع': 4, 'الرابع': 4, 'خامس': 5, 'الخامس': 5, 'سادس': 6, 'السادس': 6, 'سابع': 7, 'السابع': 7, 'ثامن': 8, 'تامن': 8, 'الثامن': 8,
       'تاسع': 9, 'التاسع': 9, 'عاشر': 10, 'العاشر': 10}

def suggest_slides(job):
    """يقترح عدد الشرايح الإجمالي (بالغلاف وCTA) من محتوى التفريغ: نقاط متسلسلة لو موجودة، وإلا حسب طول الكلام."""
    text = job.get('transcript', '') or ''
    words = len(text.split()); dur = job.get('duration', 0) or 0
    found = set()
    for w in re.findall(r'[\u0621-\u064A]+', text):
        base = re.sub(r'(ة|ه)$', '', w)
        if base in ORD: found.add(ORD[base])
        elif w in ORD: found.add(ORD[w])
    points = max(found) if len(found) >= 4 else None
    if points:
        cards = max(3, min(8, -(-points // 2)))
        basis = 'الكلام فيه %d نقاط متسلسلة (أول/تاني/…)، فهنجمع كل نقطتين في كارت' % points
    else:
        cards = max(3, min(8, round(words / 30.0)))
        basis = 'حوالي %d كلمة (%s)، فتقريبًا كارت لكل 30 كلمة' % (words, mmss(dur))
    total = max(5, min(10, cards + 2))
    reason = '%s ← %d كروت + غلاف + صفحة CTA = %d شرايح.' % (basis, cards, total)
    return {'n': total, 'reason': reason, 'words': words, 'points': points, 'options': [5, 6, 7, 8, 9, 10]}

def storyboard_stage(jid):
    """كتابة النص (storyboard) بالعدد المختار: تلقائيًا لو فيه مزوّد، وإلا استنى Claude من الشات، ثم التجهيز."""
    job = load(jid); d = jdir(jid)
    try:
        job['status'] = 'analyzing'; plan(job, [('كتابة نص الشرايح', 35)], 'story')
        (d / 'storyboard_request.md').write_text(storyboard_request(job), encoding='utf-8')
        if not (d / 'storyboard.json').exists():
            txt = None
            try: txt = call_claude(storyboard_request(job))
            except Exception as ex: logj(job, 'تعذّر توليد النص تلقائيًا (%s): %s' % (llm.provider(), ex))
            if txt:
                sbj = extract_json(txt)
                if isinstance(sbj, dict) and sbj.get('error'):
                    end_plan(job); job['status'] = 'needs_text'
                    job['transcript_quality'] = {'ok': False, 'reasons': ['النموذج رفض الكتابة لأن المصدر مش كافي: %s' % (sbj.get('reason') or sbj.get('error'))], 'words': len(job.get('transcript', '').split())}
                    logj(job, '⛔ ' + job['transcript_quality']['reasons'][0]); return
                want = job.get('slides_total')
                errs = G.validate_storyboard(normalize(copy.deepcopy(sbj)), want)
                if errs:
                    logj(job, '⚠ بنود ناقصة في النص المولَّد: ' + ' | '.join(errs[:4]) + ' — محاولة إصلاح واحدة')
                    try:
                        fix = call_claude(storyboard_request(job) + '\n---\nالنص السابق ناقص أو مخالف. صحّح الأخطاء التالية وأخرج JSON كامل من جديد (بدون أي إضافة خارج التفريغ):\n' +
                                          '\n'.join('- ' + e for e in errs) + '\nالنص السابق:\n' + json.dumps(sbj, ensure_ascii=False))
                        sbj2 = extract_json(fix); errs2 = G.validate_storyboard(normalize(copy.deepcopy(sbj2)), want)
                        if not errs2: sbj, errs = sbj2, []
                        else: errs = errs2
                    except Exception as ex:
                        logj(job, 'تعذّرت محاولة الإصلاح: %s' % ex)
                if errs:
                    (d / 'storyboard.rejected.json').write_text(json.dumps(sbj, ensure_ascii=False, indent=1), encoding='utf-8')
                    end_plan(job); job['status'] = 'needs_fix'; job['validation_errors'] = errs
                    logj(job, '⛔ بنود أساسية ناقصة في الكاروسيل — توقفت: ' + ' | '.join(errs[:5])); return
                (d / 'storyboard.json').write_text(json.dumps(sbj, ensure_ascii=False, indent=1), encoding='utf-8')
                logj(job, 'تم توليد الـ storyboard تلقائيًا')
            else:
                end_plan(job); job['status'] = 'needs_storyboard'; logj(job, 'في انتظار الـ storyboard (يُكتب في storyboard.json بواسطة Claude من الشات)'); save(job); return
        prepare(jid)
    except Exception as ex:
        job = load(jid); end_plan(job); job['status'] = 'failed'; job['error'] = str(ex); logj(job, 'فشل: %s' % ex); traceback.print_exc()

def normalize(sb):
    """يضمن وجود صفحة CTA ثابتة في آخر الكاروسيل (من محتوى الملف) + خانات الصور."""
    slides = sb.setdefault('slides', [])
    if not sb.get('cta'):
        if slides and (slides[-1].get('button') or slides[-1].get('type') == 'cta'):      # storyboard قديم: آخر شريحة كانت CTA
            last = slides.pop()
            sb['cta'] = {k: last.get(k) for k in ('tab', 'hd', 'p', 'button', 'sticker', 'image') if last.get(k) is not None}
        else:
            sb['cta'] = {'hd': [[{'t': 'عايز تعرف أكتر؟', 'c': 'hl'}]], 'p': 'اكتب **«رؤية»** في التعليقات — وهنرد عليك على الخاص.',
                         'button': 'اكتب في التعليقات', 'image': {}}
    sb['cta'].setdefault('tab', {'ar': 'تواصل', 'en': 'Contact'})
    slots = [dict(sb['cover'].get('image') or {}, id='s0', kind='cover', label='الغلاف')]
    for i, sl in enumerate(slides):
        slots.append(dict(sl.get('image') or {}, id='s%d' % (i + 1), kind='table' if sl.get('type') == 'table' else 'photo',
                          label='شريحة %d — %s' % (i + 2, (sl.get('tab') or {}).get('ar', ''))))
    slots.append(dict(sb['cta'].get('image') or {}, id='s%d' % (len(slides) + 1), kind='cta', label='شريحة %d — CTA' % (len(slides) + 2)))
    sb['_slots'] = slots; return sb

def prepare(jid):
    """بعد وجود storyboard.json: يجهّز الخانات والبرومبتات واللقطات المرشّحة ويقف عند awaiting_images."""
    job = load(jid); d = jdir(jid); project_dir(job); migrate_legacy(job); job['status'] = 'analyzing'; plan(job, [('تجهيز الانسرتات واللقطات', 12), ('التصميم المبدئي', render_est(job))], 'prepare')
    sb = normalize(json.loads((d / 'storyboard.json').read_text(encoding='utf-8')))
    errs = G.validate_storyboard(sb, job.get('slides_total'))
    if errs:
        end_plan(job); job['status'] = 'needs_fix'; job['validation_errors'] = errs
        logj(job, '⛔ بنود أساسية ناقصة في الكاروسيل — توقفت: ' + ' | '.join(errs[:5])); return
    try:
        job['grounding'] = G.verify(sb, job.get('transcript', ''))
        logj(job, ('✔ ' if not job['grounding']['bad'] else '⚠ ') + 'التأصيل: ' + job['grounding']['summary'])
        if job['grounding']['bad'] * 2 >= job['grounding']['total']:
            end_plan(job); job['status'] = 'needs_fix'
            job['validation_errors'] = ['أغلب الشرايح (%d من %d) كلامها مش موجود في التفريغ — احتمال هلوسة، تم الإيقاف' % (job['grounding']['bad'], job['grounding']['total'])]
            logj(job, '⛔ ' + job['validation_errors'][0]); return
    except Exception as ex:
        job['grounding'] = None; logj(job, 'تعذّر فحص التأصيل: %s' % ex)
    inp = d / job['input']['file']; scene = sorted(p.name for p in (d / 'frames').glob('scene_*.jpg'))
    slots = []
    for s in sb['_slots']:
        cands = []
        if job.get('has_video') and s.get('at') is not None:
            for k, off in enumerate((-2, 0, 2)):
                t = max(0, float(s['at']) + off); fn = 'frames/%s_%d.jpg' % (s['id'], k)
                run(['ffmpeg', '-y', '-ss', '%.2f' % t, '-i', str(inp), '-frames:v', '1', '-vf', 'scale=960:-2', str(d / fn)])
                if (d / fn).exists(): cands.append({'file': fn, 'label': 'ثانية %s' % mmss(t), 't': t, 'main': off == 0})
        cands += [{'file': 'frames/' + n, 'label': 'مشهد'} for n in scene[:10]] if job.get('has_video') else []
        mf = style_mf(job['style']); rd = renderer_for(job['style']); fw, fh = rd.FRAME.get(s['kind'], rd.FRAME['photo'])
        pr = imgstyle.compose(mf['image_style']['compose'].get(s['kind'], ''), s.get('prompt', ''), fw, fh)
        slots.append({'id': s['id'], 'kind': s['kind'], 'label': s['label'], 'at': s.get('at'), 'prompt': s.get('prompt', ''), 'subject': s.get('prompt', ''), 'scene_ar': s.get('scene_ar', ''), 'words': len(str(s.get('prompt', '')).split()),
                      'full_prompt': pr['positive'], 'full_negative': pr['negative'], 'ratio': '%d×%d' % (fw, fh), 'candidates': cands})
    job['slots'] = slots; job['storyboard'] = {k: v for k, v in sb.items() if k != '_slots'}
    job['neg_prompt'] = imgstyle.STYLE['negative']; save(job)
    try:
        (d / 'image_prompts.md').write_text(imgstyle.markdown(job.get('name', ''), style_mf(job['style'])['label'], slots), encoding='utf-8')
    except Exception as ex:
        logj(job, 'تعذّر كتابة image_prompts.md: %s' % ex)
    stage(job, 1)
    # تصميم مبدئي (بدون صور) قبل التوقف
    try:
        logj(job, 'التصميم المبدئي…')
        files = resolve_images(job)
        renderer_for(job['style']).build(normalize(job['storyboard']), files, d, CFG['chrome'], log=lambda m: None, outdir='out_draft', draft=True)
        job = load(jid); job.pop('results', None); job['draft'] = sorted('out_draft/' + p.name for p in (d / 'out_draft').glob('slide-*.png'))
    except Exception as ex:
        job = load(jid); logj(job, 'تعذّر التصميم المبدئي: %s' % ex)
    end_plan(job); job['status'] = 'awaiting_images'
    logj(job, '✋ توقف: الانسرتات المطلوبة جاهزة (برومبتات بنمط رؤية) — جهّز الصور وكمّل')

# ------------------------------------------------------------------ مرحلة 2: التصميم والتقفيل
def resolve_images(job):
    d = jdir(job['id']); files = {}
    folder = job.get('folder', '').strip().strip('"')
    pool = []
    if folder and os.path.isdir(folder):
        pool = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(IMG_EXT)])
    for s in job['slots']:
        sid = s['id']
        up = find_insert(job, sid)
        if up: files[sid] = str(up); continue
        ch = job.get('choices', {}).get(sid)
        if ch and (d / ch).exists():
            cand = next((c for c in s.get('candidates', []) if c['file'] == ch), None)
            if cand and cand.get('t') is not None and job.get('has_video'):
                out = d / 'images_auto'; out.mkdir(exist_ok=True); dst = out / (sid + '.jpg')
                run(['ffmpeg', '-y', '-ss', '%.2f' % cand['t'], '-i', str(d / job['input']['file']), '-frames:v', '1', '-q:v', '2', str(dst)])
                files[sid] = str(dst if dst.exists() else d / ch)
            else: files[sid] = str(d / ch)
            continue
        named = next((p for p in pool if re.match(r'^0*%s\D' % sid[1:], os.path.basename(p)) or os.path.splitext(os.path.basename(p))[0] in (sid,)), None)
        if named: files[sid] = str(save_insert(job, sid, named))
    # الصور المتبقية في الفولدر تُوزَّع بالترتيب على الخانات الفاضية
    rest = [p for p in pool if p not in files.values()]
    for s in job['slots']:
        if s['id'] not in files and rest: files[s['id']] = str(save_insert(job, s['id'], rest.pop(0)))
    # خانات فاضية: لقطة الفيديو المقترحة (أو المختارة) بدقة الفيديو الأصلية
    inp = d / job.get('input', {}).get('file', '')
    for s in job['slots']:
        sid = s['id']
        if sid in files or not job.get('has_video'): continue
        cand = next((c for c in s.get('candidates', []) if c.get('main')), None) or (s.get('candidates') or [None])[0]
        if cand and cand.get('t') is not None and inp.exists():
            out = d / 'images_auto'; out.mkdir(exist_ok=True); dst = out / (sid + '.jpg')
            run(['ffmpeg', '-y', '-ss', '%.2f' % cand['t'], '-i', str(inp), '-frames:v', '1', '-q:v', '2', str(dst)])
            if dst.exists(): files[sid] = str(dst); logj(job, 'الخانة %s: لقطة من الفيديو (%s)' % (sid, cand['label']))
    return files

def finish(jid):
    job = load(jid); d = jdir(jid)
    try:
        job['status'] = 'rendering'; plan(job, [('تجهيز الصور', 5), ('تصميم وترندر الشرايح', render_est(job)), ('تغليف النتيجة', 5)], 'finish')
        project_dir(job); migrate_legacy(job); sb = normalize(job['storyboard']); files = resolve_images(job)
        missing = [s['id'] for s in job['slots'] if s['id'] not in files]
        if missing: logj(job, 'خانات بدون صور: %s (placeholder)' % ', '.join(missing))
        stage(job, 1); logj(job, 'تصميم الشرايح وترندرها بدقة 2160×2160…')
        out_files = renderer_for(job['style']).build(sb, files, d, CFG['chrome'], log=lambda m: logj(job, m))
        stage(job, 2)
        # كابشن
        cap = job['storyboard'].get('caption', '')
        (d / 'out' / 'caption.md').write_text(cap + '\n\n— للمراجعة قبل النشر —\n' + '\n'.join('• ' + x for x in job['storyboard'].get('needs_confirmation', [])), encoding='utf-8')
        with zipfile.ZipFile(d / 'out' / 'carousel.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for f in sorted((d / 'out').iterdir()):
                if f.suffix != '.zip': z.write(f, f.name)
        job['results'] = ['out/' + Path(f).name for f in out_files]
        pd = project_dir(job); sd = pd / SUBDIRS['slides']; fd = pd / SUBDIRS['files']
        for old in sd.glob('slide-*.png'): old.unlink()
        for f in (d / 'out').iterdir():
            if f.suffix.lower() == '.png' and f.name.startswith('slide-'): shutil.copy(f, sd / f.name)
            else: shutil.copy(f, fd / f.name)
        if (d / 'image_prompts.md').exists(): shutil.copy(d / 'image_prompts.md', fd / 'image_prompts.md')
        job['delivered'] = str(pd); logj(job, '📁 اتحفظ في: %s  (الشرايح · الانسرتات · ملفات)' % pd)
        end_plan(job); job['rev'] = time.time(); job['status'] = 'done'; logj(job, '✓ تم التقفيل')
    except Exception as ex:
        job = load(jid); end_plan(job); job['status'] = 'failed'; job['error'] = str(ex); logj(job, 'فشل: %s' % ex); traceback.print_exc()

def _slot_context(job, sb, sid):
    """نص الشريحة + الجزء المناسب من التفريغ (حوالي دقيقة حوالين لحظة الشريحة)."""
    k = int(sid[1:])
    if k == 0: node, name = sb.get('cover') or {}, 'الغلاف'
    elif k <= len(sb.get('slides') or []): node, name = sb['slides'][k - 1], 'شريحة %d' % (k + 1)
    else: node, name = sb.get('cta') or {}, 'صفحة CTA'
    hd = ' / '.join(' '.join(sg if isinstance(sg, str) else sg.get('t', '') for sg in (ln if isinstance(ln, list) else [ln])) for ln in node.get('hd', []))
    txt = ' | '.join(x for x in (node.get('a'), node.get('b'), node.get('c'), hd, node.get('p'), node.get('src')) if x)
    at = (node.get('image') or {}).get('at'); lines = job.get('transcript_lines') or []
    if at is not None: seg = [l['s'] for l in lines if abs(l['t'] - float(at)) <= 40]
    else: seg = []
    if not seg: seg = [l['s'] for l in lines]
    return name, node, txt, ' '.join(seg)[:2500]

def regen_prompt(jid, sid, calls=None):
    """يولّد برومبت بديل مفصّل لخانة واحدة من نفس محتوى الشريحة والتفريغ (من غير ما يخترع). يرمي خطأ واضح لو فشل."""
    job = load(jid); sb = job.get('storyboard') or {}
    slot = next((s for s in job.get('slots', []) if s['id'] == sid), None)
    if not slot: raise ValueError('الخانة مش موجودة')
    name, node, txt, seg = _slot_context(job, sb, sid)
    prev = [slot.get('prompt', '')] + list(slot.get('prompt_history') or [])
    q = ('أنت بتكتب برومبت صورة لشريحة في كاروسيل عن فيديو. الشريحة: %s.\nنص الشريحة: %s\n\nالجزء المناسب من كلام الفيديو:\n%s\n\n'
         'اكتب برومبت **جديد ومختلف** (زاوية أو لحظة أو عنصر مختلف في نفس المرحلة) كوصف إنجليزي **مفصّل من 70 إلى 120 كلمة** لمشهد واحد محدد بيعبّر عن الجزء ده: '
         'المرحلة أو العملية، المعدة/المادة بتفاصيلها المذكورة في الكلام، الحركة الجارية، موضع الكاميرا وزاويتها وقربها، والبيئة المحيطة. '
         'ممنوع تضيف معدات أو أرقام أو معلومات مش في الكلام، وماتذكرش الأسلوب أو الإضاءة أو الألوان (بتتضاف تلقائيًا).\n'
         'البرومبتات السابقة (لازم يكون الجديد مختلف عنها):\n%s\n\nأخرج JSON فقط: {"prompt": "...", "scene_ar": "سطر عربي: أنهي جزء من الفيديو والكلام اللي بتعبّر عنه الصورة"}'
         % (name, txt, seg, '\n'.join('- ' + x for x in prev if x)))
    gen = calls or call_claude
    out = extract_json(gen(q) or '')
    pr = str(out.get('prompt', '')).strip(); words = len(pr.split())
    if words < 40 or words > 170 or sum(c.isascii() for c in pr) < len(pr) * 0.9:
        raise ValueError('البرومبت المولَّد مش مطابق (لازم إنجليزي من 40 إلى 170 كلمة، طلع %d كلمة) — جرّب تاني' % words)
    if pr.strip().lower() in [x.strip().lower() for x in prev]: raise ValueError('البرومبت المولَّد نفس القديم — جرّب تاني')
    job = load(jid); sb = job['storyboard']; k = int(sid[1:])
    node = sb['cover'] if k == 0 else (sb['slides'][k - 1] if k <= len(sb.get('slides') or []) else sb['cta'])
    img = node.setdefault('image', {}); img['prompt'] = pr; img['scene_ar'] = str(out.get('scene_ar', '')).strip()
    mf = style_mf(job['style']); rd = renderer_for(job['style'])
    for s in job['slots']:
        if s['id'] != sid: continue
        fw, fh = rd.FRAME.get(s['kind'], rd.FRAME['photo']); c = imgstyle.compose(mf['image_style']['compose'].get(s['kind'], ''), pr, fw, fh)
        s['prompt_history'] = (prev + list(s.get('prompt_history') or []))[:6]
        s.update({'prompt': pr, 'subject': pr, 'scene_ar': img['scene_ar'], 'words': words, 'full_prompt': c['positive'], 'full_negative': c['negative']})
        slot = s
    job['storyboard'] = sb; save(job)
    (jdir(jid) / 'storyboard.json').write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding='utf-8')
    try: (jdir(jid) / 'image_prompts.md').write_text(imgstyle.markdown(job.get('name', ''), mf['label'], job['slots']), encoding='utf-8')
    except Exception: pass
    return slot

def start(fn, jid): threading.Thread(target=fn, args=(jid,), daemon=True).start()
