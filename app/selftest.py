# -*- coding: utf-8 -*-
"""فحص ذاتي (بدون إنترنت وبدون أي استهلاك API) بيشتغل تلقائيًا مع كل تشغيل للسيرفر.
كل فحص هنا بيحمي من خطأ حصل قبل كده؛ لو أي فحص فشل السيرفر مش بيشتغل ويطبع السبب (تجاوز طارئ: SET SKIP_SELFTEST=1).
تشغيل يدوي:  python selftest.py"""
import os, sys, re, json, shutil, subprocess, tempfile
from pathlib import Path

APP = Path(__file__).parent
sys.path.insert(0, str(APP))


class Skip(Exception):
    pass


def _ff(args, **kw):
    return subprocess.run(args, capture_output=True, timeout=120, **kw)


# ------------------------------------------------------------------ الفحوصات
def check_tools():
    import pipeline as P
    miss = [t for t in ('ffmpeg', 'ffprobe') if not shutil.which(t)]
    if miss:
        raise RuntimeError('أدوات ناقصة على PATH: ' + ', '.join(miss))
    if not (os.environ.get('ELEVENLABS_API_KEY') or os.path.isfile(P.CFG.get('eleven_env', ''))):
        raise RuntimeError('ملف مفتاح ElevenLabs مش موجود: %s — صحّح المسار في config.json' % P.CFG.get('eleven_env'))
    if not (os.path.exists(P.CFG['chrome']) or shutil.which(P.CFG['chrome'])):
        raise RuntimeError('Chrome مش موجود في المسار: %s' % P.CFG['chrome'])
    return 'ffmpeg · ffprobe · Chrome'


def check_assets():
    need = [APP / 'image_style.json', APP / 'web' / 'index.html']
    for sid in ('november', 'october'):
        need += [APP / 'styles' / sid / 'manifest.json']
    t = APP / 'styles' / 'november' / 'template'
    need += [t / 'style.css', t / 'qr.svg', t / 'logo-white.png', t / 'ui-logo-navy.png', t / 'fonts' / 'GraphikArabic-Black.ttf']
    o = APP / 'styles' / 'october' / 'template'
    need += [o / 'build' / 'style.css', o / 'build' / 'qr.svg', o / '_system' / 'v2-base.css']
    miss = [str(x.relative_to(APP)) for x in need if not x.exists()]
    if miss:
        raise RuntimeError('ملفات ناقصة: ' + ' | '.join(miss))
    st = json.loads((APP / 'image_style.json').read_text(encoding='utf-8'))
    if not st.get('positive_base') or not st.get('negative'):
        raise RuntimeError('image_style.json ناقص (positive_base/negative)')
    return '%d ملف' % len(need)


def check_media(tmp):
    """قراءة الملفات: سليم / من غير صوت / تالف — ونتأكد إن الأخطاء واضحة ومش صامتة."""
    import pipeline as P
    av, silent, bad = tmp / 'av.mp4', tmp / 'silent.mp4', tmp / 'garbage.mp4'
    r = _ff(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=d=2:s=160x120', '-f', 'lavfi', '-i',
             'sine=frequency=440:duration=2', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(av)])
    if r.returncode != 0 or not av.exists():
        raise RuntimeError('تعذّر توليد ملف اختبار: ' + (r.stderr or b'').decode('utf-8', 'replace')[-150:])
    _ff(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=d=2:s=160x120', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(silent)])
    bad.write_bytes(b'not a media file')
    real_sleep = P.time.sleep
    P.time.sleep = lambda s: None
    try:
        dur, types = P.probe_media(av, tries=1)
        assert dur > 1 and 'audio' in types and 'video' in types, 'ملف سليم اتقرا غلط: %s %s' % (dur, types)
        dur, types = P.probe_media(silent, tries=1)
        assert 'audio' not in types, 'فيديو صامت اتعلّم إن فيه صوت'
        try:
            P.probe_media(bad, tries=1)
            raise AssertionError('ملف تالف عدّى من غير خطأ')
        except RuntimeError:
            pass
        out = tmp / 'a.mp3'
        P.extract_audio(av, out, tries=1)
        assert out.stat().st_size > 2000, 'الصوت المستخرج فاضي'
        try:
            P.extract_audio(silent, tmp / 'b.mp3', tries=1)
            raise AssertionError('استخراج صوت من فيديو صامت عدّى من غير خطأ')
        except RuntimeError:
            pass
        src, dst = tmp / 'av.mp4', tmp / 'copy.mp4'
        P.safe_copy(src, dst)
        assert dst.stat().st_size == src.stat().st_size, 'النسخ ناقص'
    finally:
        P.time.sleep = real_sleep
    return 'سليم ✔ · صامت ✔ · تالف ✔ · استخراج ✔ · نسخ ✔'


def _scribe(text, lp):
    ws = [{'type': 'word', 'text': w, 'logprob': lp, 'start': i * 0.4, 'end': i * 0.4 + 0.3} for i, w in enumerate(text.split())]
    return {'text': text, 'words': ws}


GOOD_TXT = ('موضوع مهم بخصوص تصنيع الزبادي البلدي منتشر في الأسواق. زبادي بلدي تم فيه نزع الدهن الطبيعي واستبداله بدهن نباتي. '
            'وده للأسف ما كتبوش ولا ذكره على العبوة. ونوع الدهن النباتي اللي تم إضافته نوع مهدرج. خلي بالك انت كمنتج للزبادي '
            'ما انت مش محتاج تعمل الكلام ده لأن الدهن النباتي المهدرج ضار بالصحة وبيأثر على سمعة منتجك عند المستهلك.')
BAD_TXT = ' withзион▄ sprкомиться—“ brinquants 分 手 вающая: ใ versa aren坂眷нику em姑&ಿನ zigzag蛮 as incom'


def check_transcript_gate():
    import grounding as G
    bad = G.scribe_quality(_scribe(BAD_TXT, -5.2), 52.7, -16.8)
    assert not bad['ok'], 'تفريغ معطوب (رموز/ثقة −5) عدّى من البوابة'
    low = G.scribe_quality(_scribe(GOOD_TXT, -3.0), 25, -16.8)          # نص سليم الشكل لكن ثقة Scribe منخفضة جدًا
    assert not low['ok'], 'ثقة منخفضة جدًا عدّت من البوابة'
    short = G.scribe_quality(_scribe('كلمتين بس', -0.1), 50, -16.8)
    assert not short['ok'], 'تفريغ قصير جدًا عدّى'
    good = G.scribe_quality(_scribe(GOOD_TXT, -0.1), 25, -16.8)
    assert good['ok'], 'تفريغ سليم اترفض: %s' % good['reasons']
    return 'معطوب ✔ · ثقة منخفضة ✔ · قصير ✔ · سليم ✔'


def _sb():
    img = {'prompt': 'stainless steel dairy vat', 'at': None}
    mk = lambda hd, p, tab: {'type': 'photo', 'tab': {'ar': tab, 'en': 'X'}, 'hd': [[{'t': hd, 'c': 'hl'}]], 'p': p, 'image': dict(img)}
    return {'cover': {'a': 'الدهن النباتي', 'b': 'في الزبادي البلدي', 'c': 'خلي بالك', 'image': dict(img)},
            'slides': [mk('الدهن الطبيعي اتنزع', 'الزبادي البلدي اتنزع منه الدهن الطبيعي واستبدلوه بدهن نباتي', 'الغش'),
                       mk('دهن نباتي مهدرج', 'نوع الدهن النباتي اللي اتضاف نوع مهدرج وما كتبوش على العبوة', 'النوع'),
                       mk('خلي بالك', 'ما انت مش محتاج تعمل الكلام ده كمنتج للزبادي', 'نصيحة')],
            'cta': {'hd': [[{'t': 'ناوي تصنّع زبادي؟', 'c': 'hl'}]], 'p': 'اكتب **«زبادي»** في التعليقات — وهنرد عليك على الخاص', 'button': 'اكتب في التعليقات', 'image': dict(img)},
            'caption': 'الدهن النباتي المهدرج في الزبادي البلدي — خلي بالك وراجع العبوة. #رؤية #الألبان'}


def check_storyboard_gates():
    import copy, grounding as G
    sb = _sb()
    assert G.validate_storyboard(sb, 5) == [], 'كاروسيل مكتمل اترفض: %s' % G.validate_storyboard(sb, 5)
    b = copy.deepcopy(sb); b['slides'][1]['hd'] = []; b['slides'][1]['p'] = ''; b['cta']['button'] = ''; b['caption'] = ''; b['cover']['a'] = ''
    errs = G.validate_storyboard(b, 5)
    assert len(errs) >= 5, 'بنود ناقصة ما اتكشفتش (اتكشف %d بس): %s' % (len(errs), errs)
    assert G.validate_storyboard(sb, 7), 'عدد شرايح غلط ما اتكشفش'
    rep = G.verify(sb, GOOD_TXT)
    assert rep['bad'] == 0, 'نص مؤصّل اتعلّم هلوسة: %s' % rep['summary']
    promo = {'cover': {'a': 'رؤية', 'b': 'لحلول صناعة الألبان', 'c': 'تطوير وتحديث خطوط الإنتاج'},
             'slides': [{'hd': [[{'t': 'تحسين خطوط الإنتاج', 'c': 'hl'}]], 'p': 'زيادة كفاءة التشغيل وتقليل الهدر في مصانع الألبان'},
                        {'hd': [[{'t': 'معايير السلامة', 'c': 'hl'}]], 'p': 'تطبيق أعلى معايير السلامة الغذائية لفحص الجودة'},
                        {'hd': [[{'t': 'الدعم الفني', 'c': 'hl'}]], 'p': 'تقديم استشارات هندسية متخصصة لتطوير المصانع'}],
             'cta': {'hd': [[{'t': 'طوّر مصنعك الآن', 'c': 'hl'}]], 'p': 'تواصل معنا لرفع الجودة', 'button': 'اتصل بنا'}}
    rep2 = G.verify(promo, GOOD_TXT)
    assert rep2['bad'] * 2 >= rep2['total'], 'كاروسيل دعائي من خارج الملف ما اتكشفش (هلوسة): %s' % rep2['summary']
    return 'مكتمل ✔ · بنود ناقصة ✔ · عدد غلط ✔ · مؤصّل ✔ · هلوسة ✔'


def check_prompt_style():
    import imgstyle
    r = imgstyle.compose('rule', 'A stainless steel vat', 928, 468)
    assert 'NO text' in r['positive'] and 'A stainless steel vat' in r['positive'] and 'Frame: 928x468' in r['positive'], 'البرومبت الإيجابي ناقص'
    assert 'watermark' in r['negative'] and 'human face' in r['negative'], 'البرومبت السلبي ناقص'
    return 'إيجابي + سلبي ثابتين'


def check_ui_static():
    html = (APP / 'web' / 'index.html').read_text(encoding='utf-8')
    errs = []
    if 'confirm(' in html:
        errs.append('فيه confirm() أصلي (ممكن المتصفح يحجبه ويخلي الزر ميت)')
    if 'FIN_BUSY=false;b.disabled=false' not in html:
        errs.append('زر «كمّل التصميم» ما بيرجعش يتفعّل (finally)')
    if html.count('id="finish"') != 1:
        errs.append('زر finish مكرر أو ناقص')
    if 'onclick=async()=>{\n  $(\'#finish\').disabled=true' in html:
        errs.append('معالج الزر القديم اللي بيعطّل الزر من غير إعادة تفعيل')
    banned = []
    for f in [APP / 'web' / 'index.html', APP / 'pipeline.py', APP / 'server.py', APP.parent / 'README.md']:
        if f.exists() and 'شغلان' in f.read_text(encoding='utf-8'):
            banned.append(f.name)
    if banned:
        errs.append('المصطلح الملغي «شغلان…» موجود في: ' + ', '.join(banned))
    if shutil.which('node'):
        m = re.search(r'<script>(.*)</script>', html, re.S)
        tmp = Path(tempfile.gettempdir()) / '_rooya_ui_check.js'
        tmp.write_text(m.group(1) if m else '', encoding='utf-8')
        r = subprocess.run(['node', '--check', str(tmp)], capture_output=True, text=True)
        tmp.unlink(missing_ok=True)
        if r.returncode != 0:
            errs.append('خطأ بناء في JavaScript: ' + r.stderr[:160])
    if errs:
        raise RuntimeError(' | '.join(errs))
    return 'JS ✔ · الزر ✔ · بدون confirm ✔ · المصطلحات ✔'


def _sb_promo():
    img = {'prompt': 'stainless steel dairy vat', 'at': None}
    mk = lambda hd, p, tab: {'type': 'photo', 'tab': {'ar': tab, 'en': 'X'}, 'hd': [[{'t': hd, 'c': 'hl'}]], 'p': p, 'image': dict(img)}
    return {'cover': {'a': 'رؤية', 'b': 'لحلول صناعة الألبان', 'c': 'تطوير خطوط الإنتاج', 'image': dict(img)},
            'slides': [mk('تحسين الإنتاج', 'زيادة كفاءة التشغيل وتقليل الهدر في مصانع الألبان', 'الإنتاج'),
                       mk('معايير السلامة', 'تطبيق أعلى معايير السلامة الغذائية لفحص الجودة', 'الجودة'),
                       mk('الدعم الفني', 'تقديم استشارات هندسية متخصصة لتطوير المصانع', 'الدعم')],
            'cta': {'hd': [[{'t': 'طوّر مصنعك الآن', 'c': 'hl'}]], 'p': 'تواصل معنا لرفع الجودة والكفاءة', 'button': 'اتصل بنا', 'image': dict(img)},
            'caption': 'رؤية لحلول صناعة الألبان: تطوير خطوط الإنتاج وتحسين الجودة والدعم الفني للمصانع.'}


def _fake_renderer(real):
    import types
    def build(sb, files, d, chrome, log=None, outdir='out', draft=False):
        o = Path(d) / outdir
        o.mkdir(exist_ok=True)
        n = len(sb.get('slides', [])) + 2
        made = []
        for i in range(n):
            f = o / ('slide-%02d.png' % (i + 1)); f.write_bytes(b'x'); made.append(str(f))
        if not draft: (o / 'carousel.pdf').write_bytes(b'pdf')
        build.last_files = dict(files)
        return made
    return types.SimpleNamespace(FRAME=real.FRAME, build=build)


def check_prepare_wiring():
    """prepare لازم يشغّل: التحقق من البنود الأساسية + فحص التأصيل + إيقاف الهلوسة + برومبتات إيجابي/سلبي. (اتجرّح قبل كده بالغلط وما اتكشفش)."""
    import pipeline as P
    real = P.renderer_for('november')
    fake = _fake_renderer(real)
    orig = P.renderer_for
    P.renderer_for = lambda sid: fake
    made = []
    def project(sb, transcript, total=None):
        job = P.new_job('selftest', 'november', total)
        made.append(job['id'])
        d = P.jdir(job['id'])
        (d / 'storyboard.json').write_text(json.dumps(sb, ensure_ascii=False), encoding='utf-8')
        job.update({'transcript': transcript, 'has_video': False, 'input': {'type': 'file', 'file': 'x.mp4'}}); P.save(job)
        P.prepare(job['id'])
        return P.load(job['id'])
    try:
        ok = project(_sb(), GOOD_TXT, 5)
        assert ok['status'] == 'awaiting_images', 'كاروسيل سليم ما وصلش للانسرتات: %s %s' % (ok['status'], ok.get('validation_errors'))
        assert ok.get('grounding') and ok['grounding']['bad'] == 0, 'فحص التأصيل ما اشتغلش جوه prepare (مش متوصّل)'
        s0 = ok['slots'][0]
        assert 'NO text' in s0['full_prompt'] and 'watermark' in s0['full_negative'], 'البرومبت الإيجابي/السلبي مش متركّب'
        assert (P.jdir(ok['id']) / 'image_prompts.md').exists(), 'ملف image_prompts.md ما اتكتبش'
        halluc = project(_sb_promo(), GOOD_TXT, 5)
        assert halluc['status'] == 'needs_fix' and any('هلوسة' in e for e in halluc.get('validation_errors', [])), 'كاروسيل من خارج الملف ما اتوقفش (%s)' % halluc['status']
        import copy
        sb = copy.deepcopy(_sb()); sb['cta']['button'] = ''; sb['slides'][1]['hd'] = []
        miss = project(sb, GOOD_TXT, 5)
        assert miss['status'] == 'needs_fix' and len(miss.get('validation_errors', [])) >= 2, 'بنود ناقصة ما اتوقفتش (%s)' % miss['status']
    finally:
        P.renderer_for = orig
        for jid in made:
            shutil.rmtree(P.jdir(jid), ignore_errors=True)
    return 'سليم ✔ · تأصيل متوصّل ✔ · هلوسة بتوقّف ✔ · بند ناقص بيوقّف ✔ · برومبتات ✔'


def check_analyze_wiring(tmp):
    """analyze لازم يوقف عند تفريغ معطوب، ويكمّل لاقتراح الشرايح عند تفريغ سليم (مع Scribe متحاكى)."""
    import pipeline as P, grounding as G
    av = tmp / 'av.mp4'
    if not av.exists():
        raise RuntimeError('ملف الاختبار av.mp4 مش موجود')
    real_sleep, real_scribe, real_key = P.time.sleep, P.scribe, P.read_key
    P.time.sleep = lambda s: None
    P.read_key = lambda path: 'k'
    made = []
    def run_job(scribe_result):
        P.scribe = lambda *a, **k: scribe_result
        job = P.new_job('selftest', 'november')
        made.append(job['id'])
        d = P.jdir(job['id'])
        shutil.copy(av, d / 'input.mp4')
        job['input'] = {'type': 'file', 'name': 'av.mp4'}; P.save(job)
        P.analyze(job['id'])
        return P.load(job['id'])
    try:
        bad = run_job(_scribe(BAD_TXT, -5.2))
        assert bad['status'] == 'needs_text', 'تفريغ معطوب ما وقّفش التحليل (%s)' % bad['status']
        assert not bad.get('slides_suggest'), 'التحليل كمّل لاقتراح الشرايح رغم التفريغ المعطوب'
        good = run_job(_scribe(GOOD_TXT, -0.1))
        assert good['status'] == 'awaiting_slides' and good.get('slides_suggest'), 'تفريغ سليم ما وصلش لاقتراح الشرايح (%s %s)' % (good['status'], good.get('error'))
    finally:
        P.time.sleep, P.scribe, P.read_key = real_sleep, real_scribe, real_key
        for jid in made:
            shutil.rmtree(P.jdir(jid), ignore_errors=True)
    return 'معطوب بيوقّف ✔ · سليم بيكمّل ✔'


def check_job_io():
    """كتابة/قراءة job.json بالتوازي (السيرفر بيقرا كل ثانية والخيط بيكتب) — ويندوز كان بيرمي Access denied."""
    import pipeline as P, threading
    job = P.new_job('selftest', 'november'); errs = []
    def w():
        try:
            for i in range(150): job['n'] = i; P.save(job)
        except Exception as ex: errs.append('save: %s' % ex)
    def r():
        try:
            for _ in range(300): P.load(job['id'])
        except Exception as ex: errs.append('load: %s' % ex)
    ts = [threading.Thread(target=w)] + [threading.Thread(target=r) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    shutil.rmtree(P.jdir(job['id']), ignore_errors=True)
    assert not errs, errs[0]
    return 'كتابة ×150 + قراءة متزامنة ✔'


def check_project_flow():
    """فولدر المشروع جنب المصدر + الانسرتات بأسماء الشرايح + إعادة التركيب في نفس الشريحة + إعادة توليد البرومبت + مكان الحفظ."""
    import pipeline as P, tempfile, time
    real = P.renderer_for('november'); fake = _fake_renderer(real); orig = P.renderer_for
    P.renderer_for = lambda sid: fake
    tmp = Path(tempfile.mkdtemp(prefix='rooya-proj-')); made = []
    try:
        src = tmp / 'مصدر' / 'video.mp4'; src.parent.mkdir(); src.write_bytes(b'v')
        job = P.new_job('اختبار مشروع', 'november', 5); made.append(job['id'])
        job['input'] = {'type': 'path', 'path': str(src), 'file': 'input.mp4'}; pd = P.init_project(job); P.save(job)
        assert pd.parent == src.parent and pd.name == 'اختبار مشروع', 'فولدر المشروع مش جنب المصدر: %s' % pd
        assert all((pd / v).is_dir() for v in P.SUBDIRS.values()), 'الفولدرات الفرعية ناقصة'
        j2 = P.new_job('اختبار مشروع', 'november', 5); made.append(j2['id']); j2['input'] = dict(job['input'])
        assert P.init_project(j2).name == 'اختبار مشروع (2)', 'مشروعين بنفس الاسم اتخلطوا في فولدر واحد'
        shutil.rmtree(P.jdir(j2['id']), ignore_errors=True); made.remove(j2['id']); shutil.rmtree(P.jdir(j2['id']).parent / '__none__', ignore_errors=True)
        sb = _sb(); (P.jdir(job['id']) / 'storyboard.json').write_text(json.dumps(sb, ensure_ascii=False), encoding='utf-8')
        job.update({'transcript': GOOD_TXT, 'has_video': False}); P.save(job)
        P.prepare(job['id']); job = P.load(job['id'])
        assert job['status'] == 'awaiting_images', 'prepare: %s %s' % (job['status'], job.get('validation_errors'))
        img = tmp / 'any name.jpg'; img.write_bytes(b'jpg1')
        saved = P.save_insert(job, 's2', img, '.jpg')
        assert saved.parent == pd / 'الانسرتات' and saved.name.startswith('slide-03_'), 'اسم الانسرت مش باسم الشريحة: %s' % saved.name
        assert P.find_insert(job, 's2') == saved and P.find_insert(job, 's1') is None, 'الانسرت اتربط بشريحة غلط'
        img2 = tmp / 'new.png'; img2.write_bytes(b'png2'); saved2 = P.save_insert(job, 's2', img2, '.png')
        assert len([f for f in (pd / 'الانسرتات').iterdir() if f.stem.startswith('slide-03')]) == 1, 'نسخة قديمة لنفس الشريحة فضلت'
        P.finish(job['id']); job = P.load(job['id'])
        assert job['status'] == 'done', 'finish فشل: %s' % job.get('error')
        assert Path(fake.build.last_files['s2']) == saved2, 'الصورة ما اتركّبتش في نفس الشريحة'
        assert (pd / 'الشرايح' / 'slide-01.png').exists() and (pd / 'ملفات' / 'caption.md').exists() and (pd / 'ملفات' / 'carousel.pdf').exists(), 'تسليم الفولدرات ناقص'
        # إعادة التعديل: نفس الصورة ترجع لنفس الشريحة، ولو اتبدلت يدويًا في الفولدر تتاخد النسخة الجديدة
        P.finish(job['id']); assert Path(fake.build.last_files['s2']) == saved2, 'بعد إعادة التعديل الصورة اتغيّرت'
        manual = pd / 'الانسرتات' / 'slide-03.jpg'; manual.write_bytes(b'manual'); os.utime(manual, (time.time() + 5, time.time() + 5))
        assert P.find_insert(job, 's2') == manual, 'صورة اتحطت يدويًا باسم الشريحة ما اتلقتش'
        # صور قديمة (قبل التحديث) في images/sN.jpg بتتنقل للانسرتات بأسماء الشرايح
        lj = P.new_job('قديم', 'november', 5); made.append(lj['id']); lj['input'] = {'type': 'path', 'path': str(src), 'file': 'input.mp4'}
        lj['slots'] = [{'id': 's0', 'label': 'الغلاف'}, {'id': 's1', 'label': 'شريحة 2 — الخامة'}]; (P.jdir(lj['id']) / 'images' / 's1.jpg').write_bytes(b'old')
        P.project_dir(lj); lf = P.find_insert(lj, 's1')
        assert lf and lf.parent.name == 'الانسرتات' and lf.name.startswith('slide-02_'), 'صورة قديمة ما اتنقلتش لاسم الشريحة'
        # نقل المكان
        nb = tmp / 'مكان تاني'; nb.mkdir(); job = P.load(job['id']); new = P.move_project(job, str(nb)); P.save(job)
        assert new.parent == nb and (new / 'الانسرتات').is_dir() and any((new / 'الانسرتات').iterdir()), 'نقل المشروع ماحفظش الانسرتات'
        # إعادة توليد برومبت
        job = P.load(job['id']); old = job['slots'][2]['prompt']
        good = json.dumps({'prompt': ' '.join(['stainless steel mixing tank with a large central scraper agitator rotating slowly near the wall']*6), 'scene_ar': 'مرحلة التقليب'})
        sl = P.regen_prompt(job['id'], 's2', calls=lambda q: good)
        assert sl['prompt'] != old and sl['full_prompt'].endswith(sl['prompt']) and sl['scene_ar'] == 'مرحلة التقليب' and old in sl['prompt_history'], 'إعادة التوليد ما حدّثتش الخانة'
        assert P.load(job['id'])['storyboard']['slides'][1]['image']['prompt'] == sl['prompt'], 'البرومبت الجديد ما اتحفظش في الـ storyboard'
        for bad in (json.dumps({'prompt': 'too short'}), json.dumps({'prompt': good and 'عربي ' * 60})):
            try: P.regen_prompt(job['id'], 's2', calls=lambda q, b=bad: b); raise SystemExit('برومبت غير مطابق اتقبل')
            except ValueError: pass
        # الرجوع لمرحلة من خريطة التنفيذ
        P.goto_stage(job['id'], 7); j7 = P.load(job['id'])
        assert j7['status'] == 'awaiting_images' and j7.get('slots'), 'الرجوع للانسرتات ما اشتغلش'
        P.goto_stage(job['id'], 4); j4 = P.load(job['id'])
        assert j4['status'] == 'awaiting_slides' and not j4.get('slots') and not j4.get('slides_total') and j4['slides_suggest']['n'] >= 5, 'الرجوع لعدد الشرايح ما اشتغلش'
        assert not (P.jdir(job['id']) / 'storyboard.json').exists(), 'النص القديم فضل بعد الرجوع لعدد الشرايح'
        for st in (6, 8):
            try: P.goto_stage(job['id'], st); raise SystemExit('رجوع لمرحلة ناقصة المتطلبات اتقبل: %d' % st)
            except ValueError: pass
        j4['status'] = 'analyzing'; P.save(j4)
        try: P.goto_stage(job['id'], 7); raise SystemExit('الرجوع اتقبل والمشروع شغّال')
        except ValueError: pass
    finally:
        P.renderer_for = orig
        for jid in made: shutil.rmtree(P.jdir(jid), ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return 'جنب المصدر ✔ · أسماء الشرايح ✔ · إعادة تركيب ✔ · نقل المكان ✔ · إعادة توليد ✔'


def check_jobs_dir():
    import pipeline as P
    t = P.JOBS / '.write_test'
    t.write_text('ok'); t.unlink()
    return str(P.JOBS)


CHECKS = [('أدوات النظام', check_tools), ('الملفات والقوالب', check_assets), ('قراءة الملفات والصوت', 'media'), ('بوابة جودة التفريغ', check_transcript_gate),
          ('البنود الأساسية والتأصيل', check_storyboard_gates), ('نمط برومبتات الصور', check_prompt_style), ('توصيل المسار: prepare', check_prepare_wiring), ('توصيل المسار: analyze', 'analyze'), ('كتابة/قراءة حالة الكاروسيل', check_job_io), ('فولدر المشروع والانسرتات', check_project_flow), ('الواجهة (ثوابت الأعطال القديمة)', check_ui_static),
          ('فولدر الكاروسيلات', check_jobs_dir)]


def run(verbose=True):
    tmp = Path(tempfile.mkdtemp(prefix='rooya_selftest_'))
    rows, ok = [], True
    for name, fn in CHECKS:
        try:
            d = check_media(tmp) if fn == 'media' else (check_analyze_wiring(tmp) if fn == 'analyze' else fn())
            rows.append((name, 'PASS', d))
        except Skip as e:
            rows.append((name, 'SKIP', str(e)))
        except Exception as e:
            ok = False
            rows.append((name, 'FAIL', (str(e) or e.__class__.__name__)[:300]))
    shutil.rmtree(tmp, ignore_errors=True)
    lines = ['%s  %-34s %s' % ({'PASS': '✔', 'FAIL': '✘', 'SKIP': '–'}[s], n, d) for n, s, d in rows]
    report = '\n'.join(lines)
    try:
        (APP / 'selftest_report.txt').write_text(report, encoding='utf-8')
    except OSError:
        pass
    if verbose:
        print('الفحص الذاتي:\n' + report, flush=True)
    return ok


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
