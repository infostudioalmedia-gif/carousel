# -*- coding: utf-8 -*-
r"""نشر السيستم على Hugging Face Space (خاص). الاستخدام:
   python hf/deploy.py --user HF_USERNAME --space rooya-carousel --token-file "C:\...\HF TOKEN .env" --password كلمة_دخول_للفريق
المفاتيح (ElevenLabs/Gemini) بتتقرا من ملفاتها المحلية وتتبعت كـ Secrets مشفّرة، وما بتتطبعش ولا بتتكتب في أي ملف."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))

def tok(path):
    t = open(path, encoding='utf-8-sig').read(); m = re.search(r'(hf_[A-Za-z0-9]+)', t); return m.group(1) if m else t.strip().split()[0]

def api(method, url, token, body=None):
    r = urllib.request.Request('https://huggingface.co' + url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=60) as x: return x.status, x.read().decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e: return e.code, e.read().decode('utf-8', 'ignore')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--user', required=True); ap.add_argument('--space', default='rooya-carousel')
    ap.add_argument('--token-file', required=True); ap.add_argument('--password', required=True); a = ap.parse_args()
    token = tok(a.token_file); repo = '%s/%s' % (a.user, a.space)
    code, out = api('POST', '/api/repos/create', token, {'type': 'space', 'name': a.space, 'sdk': 'docker', 'private': True})
    print('إنشاء الـ Space:', code, '(409 = موجود)' if code == 409 else '')
    if code not in (200, 409): print(out[:300]); sys.exit(1)
    import pipeline as P
    secrets = {'ROOYA_PASSWORD': a.password}
    try: secrets['ELEVENLABS_API_KEY'] = P.read_key(P.CFG['eleven_env'])
    except Exception as ex: print('⚠ مفتاح ElevenLabs مش متقري:', type(ex).__name__)
    from llm import gemini_key
    if gemini_key(): secrets['GEMINI_API_KEY'] = gemini_key()
    for k, v in secrets.items():
        c, _ = api('POST', '/api/spaces/%s/secrets' % repo, token, {'key': k, 'value': v}); print('Secret', k, '→', c)
    tmp = Path(tempfile.mkdtemp(prefix='rooya-space-'))
    shutil.copytree(ROOT / 'app', tmp / 'app', ignore=shutil.ignore_patterns('__pycache__', 'config.json', '.llm_*', 'selftest_report.txt'))
    shutil.copy(ROOT / 'hf' / 'Dockerfile', tmp / 'Dockerfile'); shutil.copy(ROOT / 'hf' / 'README_space.md', tmp / 'README.md')
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    g = lambda *c: subprocess.run(['git', '-c', 'http.extraHeader=Authorization: Bearer ' + token, '-c', 'core.autocrlf=false'] + list(c), cwd=tmp, env=env, capture_output=True, text=True)
    g('init', '-q', '-b', 'main'); g('add', '-f', '-A'); g('-c', 'user.name=rooya', '-c', 'user.email=rooya@example.com', 'commit', '-q', '-m', 'deploy')
    r = g('push', '-f', 'https://huggingface.co/spaces/%s' % repo, 'main')
    print('الرفع:', 'تمام ✔' if r.returncode == 0 else r.stderr.replace(token, '***')[:400])
    shutil.rmtree(tmp, ignore_errors=True)
    print('الرابط: https://huggingface.co/spaces/%s  (البناء بياخد كام دقيقة)' % repo)
main()
