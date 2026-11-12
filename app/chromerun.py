# -*- coding: utf-8 -*-
"""تشغيل Chrome headless للتصوير: بروفايل معزول (ما يتعارضش مع كروم المستخدم) + إعادة محاولة لو علّق."""
import subprocess, tempfile, shutil, time, os

def shot(chrome, args, timeout=150, tries=3):
    last = None
    for k in range(tries):
        prof = tempfile.mkdtemp(prefix='rooya-chrome-')
        p = subprocess.Popen([chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                              '--user-data-dir=' + prof] + (['--no-sandbox', '--disable-dev-shm-usage'] if os.environ.get('ROOYA_NOSANDBOX') else []) + list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            p.wait(timeout=timeout); return
        except subprocess.TimeoutExpired as ex:
            last = ex
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        finally:
            shutil.rmtree(prof, ignore_errors=True)
    raise RuntimeError('Chrome علّق %d مرات متتالية عند التصوير (%s)' % (tries, last))
