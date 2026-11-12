# -*- coding: utf-8 -*-
"""نمط «كاروسيل أكتوبر»: صورة بملء الشريحة + جريدانت سفلي + بطاقات زجاجية. نفس الـ storyboard، رندر مختلف (شريحة لكل لقطة شاشة)."""
import os, re, html, shutil, subprocess, time
import chromerun
from pathlib import Path
from PIL import Image

APP = Path(__file__).parent
TPL = APP / 'styles' / 'october' / 'template'
FRAME = {'cover': (1080, 700), 'photo': (1080, 1080), 'cta': (1080, 1080), 'table': (1080, 1080)}
TAG = '<span class="tagline">رؤية لحلول صناعة الألبان</span>'
CK = '<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="#4FE6D5"/><path d="M12.6 20.6l5 5 10-11" fill="none" stroke="#07403B" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def esc(s): return html.escape(str(s), quote=False)
def rich(s): return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', esc(s))

def fit_image(src, kind, dst):
    """قص بنسبة الإطار مع تفضيل أعلى الصورة (الموضوع فوق، والجريدانت تحت). ألوان طبيعية."""
    w, h = FRAME.get(kind, FRAME['photo']); ar = w / h
    im = Image.open(src).convert('RGB'); iw, ih = im.size
    if iw / ih > ar: nw = int(ih * ar); x0 = (iw - nw) // 2; im = im.crop((x0, 0, x0 + nw, ih))
    else: nh = int(iw / ar); im = im.crop((0, 0, iw, nh))
    if im.width < 2200: im = im.resize((2200, int(im.height * 2200 / im.width)), Image.LANCZOS)
    im.save(dst, quality=95, subsampling=0)

def placeholder(kind, dst, label):
    from PIL import ImageDraw, ImageFont
    w, h = FRAME.get(kind, FRAME['photo']); im = Image.new('RGB', (w * 2, h * 2), (30, 50, 110)); d = ImageDraw.Draw(im)
    for x in range(0, w * 2, 48):
        for y in range(0, h * 2, 48): d.ellipse((x, y, x + 4, y + 4), fill=(70, 100, 170))
    try: f = ImageFont.truetype(str(TPL / 'fonts' / 'GraphikArabic-Black.ttf'), 150)
    except Exception: f = None
    t = 'INSERT %s' % label[1:]; bb = d.textbbox((0, 0), t, font=f)
    d.text(((w * 2 - (bb[2] - bb[0])) / 2, (h * 2 // 3 - (bb[3] - bb[1])) / 2), t, fill=(79, 230, 213), font=f)
    im.save(dst, quality=92)

def h2_html(hd):
    out = []
    for i, line in enumerate(hd):
        segs = line if isinstance(line, list) else [line]
        txt = ' '.join(esc(s if isinstance(s, str) else s['t']) for s in segs)
        out.append(txt if i == 0 else '<span class="ac">%s</span>' % txt)
    return '<br>'.join(out)

def pager(i, n): return '<div class="rule"></div>\n  <span class="pager">%02d / %02d</span>\n  %s' % (i, n, TAG)

def cover(sb, slot, n):
    c = sb['cover']; quote = c.get('quote') or ' · '.join(c.get('strip', []))
    return ('<section class="slide cover"><div class="bg"></div><div class="dots"></div>'
            '<div class="photo"><img src="%s" alt=""></div><span class="scrim-bot" style="z-index:1"></span>'
            '<img class="brand" src="logo-white.png" alt="" style="z-index:3">'
            '<div class="block" style="z-index:2"><h1 class="h1"><span class="gd">%s</span><br><span class="ac">%s</span></h1>'
            '<div class="quote">%s</div></div><div class="swipe"><span>اسحب</span><span>←</span></div></section>') % (
        slot['file'], esc(c.get('a', '')), esc((c.get('b', '') + ' ' + c.get('c', '')).strip()),
        ('<b style="color:var(--teal)">%s</b>' % esc(quote)) if quote else '')

def content(sb, i, sl, slot, n):
    pts = ''
    for k, p in enumerate(sl.get('points', []), 1):
        pts += '<div class="pt"><i>%d</i><p>%s</p></div>' % (k, rich(p))
    for r in sl.get('rows', []) or []:
        pts += '<div class="pt"><i>%s</i><p><b>%s</b> %s %s</p></div>' % (CK, esc(r.get('k', '')), esc(r.get('v', '')), esc(r.get('small', '')))
    if sl.get('chips'):
        pts += '<div class="pt"><i>%s</i><p>%s</p></div>' % (CK, ' · '.join('<b>%s</b>' % esc(c) for c in sl['chips']))
    bar = '<div class="bar go" style="margin-top:var(--s2)">%s</div>' % rich(sl['p']) if sl.get('p') else ''
    return ('<section class="slide fb cmp"><div class="bg"></div><div class="ph"><img src="%s" alt="" style="width:1080px;left:0;top:0"></div>'
            '<div class="fade"></div><div class="scrim-top"></div><img class="brand" src="logo-white.png" alt="">'
            '<span class="stitle">%s</span><div class="wrap"><h2 class="h2">%s</h2><div class="pts">%s</div>%s</div>%s</section>') % (
        slot['file'], esc((sl.get('tab') or {}).get('ar', '')), h2_html(sl.get('hd', [])), pts, bar, pager(i + 2, n))

def cta(sb, sl, slot, n):
    return ('<section class="slide cta fb"><div class="bg"></div><div class="ph"><img src="%s" alt="" style="width:1080px;left:0;top:0"></div>'
            '<div class="fade"></div><div class="scrim-top"></div><img class="brand" src="logo-white.png" alt="">'
            '<div class="body"><span class="eyebrow">%s</span><h2 class="h2">%s</h2><p class="lede">%s</p><p class="ask">%s</p></div>'
            '<div class="foot"><span class="qr"><img src="qr.svg" alt=""></span><span class="who"><p>تدريب حقيقي جوّه مصنع · استشارات · تطوير مصانع</p></span></div></section>') % (
        slot['file'], esc(sl.get('eyebrow') or 'رؤية · خبراء صناعة الألبان'), h2_html(sl.get('hd', [])),
        rich(sl.get('p', '')), esc(sl.get('button', '')))

def build(sb, slot_files, workdir, chrome, log=print, outdir='out', draft=False):
    work = Path(workdir); src = work / '_src'; b = src / 'build'; b.mkdir(parents=True, exist_ok=True)
    for d in ('_system', 'fonts'):
        if not (src / d).exists(): shutil.copytree(TPL / d, src / d)
    for f in ('style.css', 'logo-white.png', 'qr.svg'): shutil.copy(TPL / 'build' / f, b / f)
    slots = sb['_slots']
    for s in slots:
        dst = b / ('art-%s.jpg' % s['id']); p = slot_files.get(s['id'])
        if p and os.path.exists(p): fit_image(p, s['kind'], dst)
        else: placeholder(s['kind'], dst, s['id']); log('تحذير: لا توجد صورة للخانة %s — placeholder' % s['id'])
        s['file'] = 'art-%s.jpg' % s['id']
    slides = sb['slides']; n = len(slides) + 2; pages = [cover(sb, slots[0], n)]
    for i, sl in enumerate(slides):
        pages.append(content(sb, i, sl, slots[i + 1], n))
    pages.append(cta(sb, sb['cta'], slots[len(slides) + 1], n))
    out = work / outdir; out.mkdir(exist_ok=True); files = []
    for i, pg in enumerate(pages):
        doc = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body>%s</body></html>' % pg
        (b / ('p%d.html' % i)).write_text(doc, encoding='utf-8'); shot = b / ('_p%d.png' % i)
        chromerun.shot(chrome, ['--hide-scrollbars', '--allow-file-access-from-files',
                        '--force-device-scale-factor=2', '--window-size=1080,1080', '--screenshot=' + str(shot),
                        '--virtual-time-budget=7000', 'file:///' + str(b / ('p%d.html' % i)).replace('\\', '/')])
        im = Image.open(shot).convert('RGB'); p = out / ('slide-%02d.png' % (i + 1))
        for _ in range(8):
            try: im.save(p, 'PNG'); break
            except OSError: time.sleep(1)
        files.append(str(p))
    imgs = [Image.open(p).convert('RGB') for p in files]
    imgs[0].save(out / 'carousel.pdf', save_all=True, append_images=imgs[1:], resolution=200)
    return files
