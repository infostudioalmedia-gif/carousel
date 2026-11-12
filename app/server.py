# -*- coding: utf-8 -*-
"""سيرفر محلي خفيف (stdlib فقط) لخدمة «كاروسيل نوفمبر» — تشغيل: python server.py  ثم افتح http://localhost:8765"""
import os, re, json, time, mimetypes, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import pipeline as P

WEB = Path(__file__).parent / 'web'

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def body_json(self):
        n = int(self.headers.get('Content-Length', 0)); return json.loads(self.rfile.read(n) or b'{}')
    def save_body(self, dst):
        n = int(self.headers.get('Content-Length', 0)); left = n
        with open(dst, 'wb') as f:
            while left > 0:
                ch = self.rfile.read(min(1 << 20, left));
                if not ch: break
                f.write(ch); left -= len(ch)
    def serve_file(self, p):
        if not p.is_file(): return self.send_json({'error': 'not found'}, 404)
        data = p.read_bytes(); ct = mimetypes.guess_type(str(p))[0] or 'application/octet-stream'
        self.send_response(200); self.send_header('Content-Type', ct + ('; charset=utf-8' if ct.startswith('text') else ''))
        self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-cache'); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); path = urllib.parse.unquote(u.path)
        if path in ('/', '/index.html'): return self.serve_file(WEB / 'index.html')
        if path == '/api/styles': return self.send_json(P.list_styles())
        if path == '/api/health': return self.send_json({'provider': P.llm.provider(), 'last': P.llm.last_status(), 'now': time.time()})
        if path == '/api/jobs':
            jobs = []
            for d in sorted(P.JOBS.iterdir(), reverse=True)[:15]:
                if (d / 'job.json').exists():
                    j = P.load(d.name); jobs.append({k: j.get(k) for k in ('id', 'name', 'status')})
            return self.send_json(jobs)
        m = re.match(r'^/api/jobs/([\w-]+)$', path)
        if m:
            jid = m.group(1)
            if not (P.jdir(jid) / 'job.json').exists(): return self.send_json({'error': 'not found'}, 404)
            j = P.load(jid)
            # تلقائيًا: لو الـ storyboard اتكتب بعد الانتظار → كمّل التجهيز
            if j['status'] == 'needs_storyboard' and (P.jdir(jid) / 'storyboard.json').exists():
                j['status'] = 'analyzing'; P.save(j); P.start(P.prepare, jid)
            imgs = P.jdir(jid) / 'images'
            j['uploaded'] = sorted({q.stem for q in imgs.glob('*.*') if q.suffix.lower() in P.IMG_EXT}) if imgs.is_dir() else []
            j['uploaded_files'] = {q.stem: q.name for q in sorted(imgs.glob('*.*')) if q.suffix.lower() in P.IMG_EXT} if imgs.is_dir() else {}
            j['now'] = time.time(); return self.send_json(j)
        m = re.match(r'^/fonts/([\w.-]+\.(?:ttf|otf))$', path)
        if m: return self.serve_file(P.STYLES_DIR / 'november' / 'template' / 'fonts' / m.group(1))
        if path == '/logo.png': return self.serve_file(P.STYLES_DIR / 'november' / 'template' / 'ui-logo-navy.png')
        m = re.match(r'^/styles/([\w-]+)/thumb$', path)
        if m: return self.serve_file(P.STYLES_DIR / m.group(1) / 'thumb.jpg')
        m = re.match(r'^/files/([\w-]+)/(.+)$', path)
        if m:
            base = P.jdir(m.group(1)).resolve(); p = (base / m.group(2)).resolve()
            if base not in p.parents: return self.send_json({'error': 'forbidden'}, 403)
            return self.serve_file(p)
        self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path); path = u.path; q = urllib.parse.parse_qs(u.query)
        try:
            if path == '/api/jobs/new':           # رفع ملف خام: الجسم = bytes
                name = urllib.parse.unquote(q.get('name', [''])[0]); fn = urllib.parse.unquote(q.get('filename', ['input.bin'])[0])
                job = P.new_job(name, q.get('style', [None])[0], int(q['slides'][0]) if q.get('slides', [''])[0].isdigit() else None); ext = os.path.splitext(fn)[1].lower() or '.bin'
                self.save_body(P.jdir(job['id']) / ('input' + ext))
                job['input'] = {'type': 'file', 'name': fn}; P.save(job); P.start(P.analyze, job['id']); return self.send_json({'id': job['id']})
            if path == '/api/jobs/new-url':
                b = self.body_json(); job = P.new_job(b.get('name', ''), b.get('style'), int(b['slides']) if str(b.get('slides', '')).isdigit() else None)
                u0 = P.clean_path(b['url'])
                job['input'] = {'type': 'path', 'path': u0} if P.is_local_file(u0) else {'type': 'url', 'url': u0}; P.save(job); P.start(P.analyze, job['id']); return self.send_json({'id': job['id']})
            m = re.match(r'^/api/jobs/([\w-]+)/(upload|update|finish|retry|slides|source_text|restart)$', path)
            if m:
                jid, act = m.groups(); job = P.load(jid)
                if act == 'upload':
                    slot = q.get('slot', [''])[0]; fn = urllib.parse.unquote(q.get('filename', ['x.jpg'])[0])
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in P.IMG_EXT: return self.send_json({'error': 'صيغة غير مدعومة'}, 400)
                    for old in (P.jdir(jid) / 'images').glob(slot + '.*'): old.unlink()
                    self.save_body(P.jdir(jid) / 'images' / (slot + ext)); return self.send_json({'ok': True})
                if act == 'update':
                    b = self.body_json()
                    if 'storyboard' in b: job['storyboard'] = b['storyboard']
                    restyle = 'style' in b and b['style'] != job.get('style')
                    for k in ('choices', 'folder', 'out', 'style'):
                        if k in b: job[k] = b[k]
                    if restyle: job['status'] = 'analyzing'
                    P.save(job)
                    if restyle: P.start(P.prepare, jid)      # يعيد البرومبتات والتصميم المبدئي بالنمط الجديد
                    return self.send_json({'ok': True})
                if act == 'finish':
                    job['status'] = 'rendering'; P.save(job); P.start(P.finish, jid); return self.send_json({'ok': True})
                if act == 'slides':
                    b = self.body_json(); n = int(b.get('n', 0))
                    if n < 5 or n > 10: return self.send_json({'error': 'عدد الشرايح من 5 إلى 10'}, 400)
                    tx = (b.get('transcript') or '').strip()
                    if tx and tx != (job.get('transcript') or '').strip():
                        job['transcript'] = tx; job['transcript_lines'] = P.G.lines_from_text(tx, job.get('duration', 0)); job['source_text'] = True
                        P.logj(job, 'تم تعديل التفريغ يدويًا قبل كتابة النص')
                    job['slides_total'] = n; job['slides_confirmed'] = True; job['status'] = 'analyzing'; P.save(job)
                    P.start(P.storyboard_stage, jid); return self.send_json({'ok': True})
                if act == 'source_text':
                    b = self.body_json(); text = (b.get('text') or '').strip()
                    if len(text.split()) < 25: return self.send_json({'error': 'النص قصير (أقل من 25 كلمة) — الصق السكريبت أو الكلام كامل'}, 400)
                    job['transcript'] = text; job['transcript_lines'] = P.G.lines_from_text(text, job.get('duration', 0)); job['source_text'] = True
                    job['transcript_quality'] = {'ok': True, 'reasons': [], 'words': len(text.split()), 'user': True}
                    sbf = P.jdir(jid) / 'storyboard.json'
                    if sbf.exists(): sbf.rename(sbf.with_suffix('.rejected.json'))        # نص قديم مبني على تفريغ مرفوض
                    P.logj(job, 'تم اعتماد نص من المستخدم (%d كلمة)' % len(text.split()))
                    if job.get('slides_total'):
                        job['slides_confirmed'] = True; job['status'] = 'analyzing'; P.save(job); P.start(P.storyboard_stage, jid)
                    else:
                        job['slides_suggest'] = P.suggest_slides(job); job['status'] = 'awaiting_slides'; P.save(job)
                    return self.send_json({'ok': True})
                if act == 'restart':
                    if job.get('status') in ('received', 'analyzing', 'rendering'): return self.send_json({'error': 'الكاروسيل شغّال دلوقتي'}, 409)
                    P.reset_job(jid); P.start(P.analyze, jid); return self.send_json({'ok': True})
                if act == 'retry':
                    j2 = P.load(jid); j2['status'] = 'analyzing'; j2.pop('error', None); P.save(j2)
                    P.start(P.prepare if j2.get('slots') else (P.storyboard_stage if (j2.get('transcript') and j2.get('slides_confirmed')) else P.analyze), jid); return self.send_json({'ok': True})
        except Exception as ex:
            return self.send_json({'error': str(ex)}, 500)
        self.send_json({'error': 'not found'}, 404)

if __name__ == '__main__':
    if not os.environ.get('SKIP_SELFTEST') and not os.environ.get('ROOYA_PRECHECKED'):
        import selftest
        if not selftest.run():
            print('\n⛔ الفحص الذاتي فشل — السيرفر مش هيشتغل لحد ما العطل يتصلّح (الفحص ده بيحمي من أخطاء حصلت قبل كده).', flush=True)
            raise SystemExit(1)
    P.recover(); port = P.CFG.get('port', 8765)
    print('سيستم كاروسيل رؤية — http://localhost:%d' % port, flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
