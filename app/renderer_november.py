# -*- coding: utf-8 -*-
"""يحوّل storyboard.json + صور الخانات إلى شرائح «كاروسيل نوفمبر» (1080×1080 → PNG 2160)."""
import os, re, html, shutil, subprocess, time
import chromerun
from pathlib import Path
from PIL import Image

APP = Path(__file__).parent
TPL = APP / 'styles' / 'november' / 'template'
PH, TX, PH2 = 468, 290, 290
# نسبة إطار كل نوع صورة (عرض×ارتفاع بالبكسل داخل الشريحة)
FRAME = {'cover': (1080, 1080), 'photo': (928, 468), 'cta': (928, 410), 'table': (928, 290)}

def esc(s): return html.escape(str(s), quote=False)
def rich(s):
    s = esc(s)
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)

def spark(style):
    return ('<svg class="spark" style="%s" viewBox="0 0 44 44"><path d="M22 0C24 14 30 20 44 22C30 24 24 30 22 44C20 30 14 24 0 22C14 20 20 14 22 0Z" fill="#fff"/></svg>' % style)
CALC = '''<svg width="170" height="170" viewBox="0 0 200 200" fill="none" stroke="#0E1634" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"><rect x="36" y="14" width="128" height="172" rx="24" fill="#4FE6D5"/><rect x="56" y="34" width="88" height="38" rx="10" fill="#fff"/><path d="M118 53h14" stroke-width="6"/><g fill="#0E1634" stroke="none"><circle cx="68" cy="102" r="9"/><circle cx="100" cy="102" r="9"/><circle cx="132" cy="102" r="9"/><circle cx="68" cy="132" r="9"/><circle cx="100" cy="132" r="9"/><circle cx="132" cy="132" r="9"/><circle cx="68" cy="162" r="9"/><circle cx="100" cy="162" r="9"/></g><circle cx="132" cy="162" r="10" fill="#FFD27A"/></svg>'''
CAL = '''<svg width="144" height="144" viewBox="0 0 200 200" fill="none" stroke="#0E1634" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"><rect x="20" y="36" width="150" height="140" rx="20" fill="#fff"/><path d="M20 56a20 20 0 0 1 20-20h110a20 20 0 0 1 20 20v22H20z" fill="#4FE6D5"/><path d="M60 18v34M130 18v34"/><g fill="#0E1634" stroke="none"><circle cx="52" cy="106" r="7"/><circle cx="82" cy="106" r="7"/><circle cx="112" cy="106" r="7"/><circle cx="52" cy="136" r="7"/><circle cx="82" cy="136" r="7"/></g><circle cx="146" cy="142" r="40" fill="#FFD27A"/><path d="M146 118v26l16 10"/></svg>'''
XC = '<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="#FF8A8A"/><path d="M13.5 13.5l13 13M26.5 13.5l-13 13" stroke="#5A1414" stroke-width="3.6" stroke-linecap="round"/></svg>'
CKC = '<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="#4FE6D5"/><path d="M12.6 20.6l5 5 10-11" fill="none" stroke="#07403B" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICONS = ('<svg viewBox="0 0 34 34"><path d="M17 29S4 21 4 12.5A6.5 6.5 0 0 1 17 9a6.5 6.5 0 0 1 13 3.5C30 21 17 29 17 29z"/></svg>'
         '<svg viewBox="0 0 34 34"><path d="M6 8h22a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H15l-7 5v-5H6a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z"/></svg>'
         '<svg viewBox="0 0 34 34"><path d="M9 4h16v26l-8-6-8 6z"/></svg>'
         '<svg viewBox="0 0 34 34"><path d="M30 4L4 14l9 5 4 10zM13 19L30 4"/></svg>')
SWIPE = ('<span class="swipe"><span>اسحب</span><svg viewBox="0 0 150 44" fill="none" stroke="#4FE6D5" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M144 30C120 4 96 4 76 20S34 36 8 16"/><path d="M22 6L7 15L21 28"/></svg></span>')
STICK = {'calc': CALC, 'cal': CAL}

def hd_html(hd):
    lines = []
    for line in hd:
        segs = line if isinstance(line, list) else [line]
        parts = []
        for sg in segs:
            if isinstance(sg, str): sg = {'t': sg, 'c': 'hl'}
            c = sg.get('c', 'hl')
            parts.append('<span class="%s">%s</span>' % (c, esc(sg['t'])) if c else esc(sg['t']))
        lines.append(' '.join(parts))
    return '<br>'.join(lines)

def top(): return '<div class="top"><img src="logo-white.png" alt=""><span class="pill tl">خلّينا نشرحلك</span></div>'
def foot(last): return '<div class="foot"><div class="r"><span class="ic">%s</span>%s</div></div>' % (ICONS, '' if last else SWIPE)
def tabs_html(tabs, active):
    n = len(tabs); cls = ' t9' if n >= 9 else (' t8' if n == 8 else (' t7' if n == 7 else ''))   # تصغير الخط لما التابات تكتر
    return '<div class="tabs%s">%s</div>' % (cls, ''.join(
        '<div class="tab%s">%s<small>%s</small></div>' % (' on' if i == active else '', esc(t.get('ar', '')), esc(t.get('en', '')))
        for i, t in enumerate(tabs)))
def card(tabs, active, inner, last):
    return '<section class="slide">%s<div class="fold">%s<div class="fcard">%s</div></div>%s</section>' % (
        top(), tabs_html(tabs, active), inner, foot(last))

def img_tag(slot): return '<img src="%s" alt="">' % slot['file']

def cover_html(sb, slot, last=False):
    """غلاف: صورة بملء الشريحة بدون فريم + تلاشي لكحلي الخلفية + العناوين والمستطيل فوقها."""
    c = sb['cover']
    b = esc(c.get('b', ''))
    acc = c.get('accent')
    if acc and esc(acc) in b:
        b = b.replace(esc(acc), '<span class="n">%s</span>' % esc(acc), 1)
    strip = ''
    if c.get('strip'):
        strip = '<div class="cv-strip"><div class="strip">%s</div></div>' % '<i></i>'.join('<span>%s</span>' % esc(x) for x in c['strip'])
    stk = ''
    if c.get('sticker') in STICK:
        stk = '<div class="stk" style="left:55px;top:462px;transform:rotate(-8deg);">%s</div>%s' % (
            STICK[c['sticker']], spark('left:236px;top:470px'))
    return ('<section class="slide"><div class="cv-ph">%s</div><div class="cv-top"></div><div class="cv-fade"></div><div class="cv-dots"></div>'
            '%s%s<div class="cv-text"><div class="ha"><span class="hl">%s</span></div><div class="hb">%s</div><div class="hc">%s</div></div>%s'
            '<div class="foot"><div class="r"><span class="ic">%s</span>%s</div></div></section>') % (
        img_tag(slot), top(), stk, esc(c.get('a', '')), b, esc(c.get('c', '')), strip, ICONS, SWIPE)

def cta_html(sb, slot, tabs, active):
    """صفحة CTA ثابتة: صورة + عنوان/نص من محتوى الملف + زر + باركود رؤية."""
    c = sb['cta']
    over = '<div class="stk" style="right:-8px;top:-44px;transform:rotate(6deg);">%s</div>' % CAL if c.get('sticker') == 'cal' else ''
    inner = ('<div style="position:relative;flex:none"><div class="ph" style="height:%dpx">%s</div>%s</div>'
             '<div class="txt ctarow"><div class="cap" style="flex:1;min-width:0"><div class="hd">%s</div>%s%s</div>'
             '<div class="qrb"><img src="qr.svg" alt=""><span>امسح الباركود</span></div></div>') % (
        FRAME['cta'][1], img_tag(slot), over, hd_html(c.get('hd', [])),
        ('<p>%s</p>' % rich(c['p'])) if c.get('p') else '',
        ('<div class="cta-btn"><span>%s</span></div>' % esc(c['button'])) if c.get('button') else '')
    return card(tabs, active, inner, True)

def slide_html(sb, i, slide, slot, tabs, last):
    t = slide.get('type', 'photo')
    cap = '<div class="cap"><div class="hd">%s</div>%s</div>' % (hd_html(slide.get('hd', [])),
          ('<p>%s</p>' % rich(slide['p'])) if slide.get('p') else '')
    if t == 'table':
        rows = ''.join('<div class="tr"><div class="k">%s</div><div class="v">%s%s</div></div>' % (
            esc(r.get('k', '')), esc(r.get('v', '')), ('<small>%s</small>' % esc(r['small'])) if r.get('small') else '')
            for r in slide.get('rows', []))
        inner = ('<div class="ph" style="height:%dpx">%s</div><div class="txt" style="justify-content:flex-start">'
                 '<div class="cap" style="margin-top:21px"><div class="hd">%s</div></div><div class="tbl">%s</div></div>') % (
            PH2, img_tag(slot), hd_html(slide.get('hd', [])), rows)
        return card(tabs, i, inner, last)
    over = ''
    if slide.get('badge'):
        over += '<div class="badge" style="right:-3px;top:-26px;transform:rotate(4deg)">%s</div>' % esc(slide['badge'])
    if slide.get('chips'):
        ic = XC if slide.get('chips_icon') == 'x' else CKC
        over += '<div class="chips">%s</div>' % ''.join('<span class="chip">%s %s</span>' % (ic, esc(c)) for c in slide['chips'])
    if slide.get('sticker') in STICK:
        over += '<div class="stk" style="right:-8px;top:-44px;transform:rotate(6deg);">%s</div>' % STICK[slide['sticker']]
    extra = ''
    if slide.get('slider'):
        s = slide['slider']
        extra += ('<div class="rows"><div class="rw"><span class="l">%s</span><span class="ln"><i class="dot" style="left:6%%;"></i></span>'
                  '<span class="r">%s</span></div></div>') % (esc(s.get('start', '')), esc(s.get('end', '')))
    if slide.get('button'):
        extra += '<div class="cta-btn"><span>%s</span></div>' % esc(slide['button'])
    inner = ('<div style="position:relative;flex:none"><div class="ph" style="height:%dpx">%s</div>%s</div>'
             '<div class="txt cap"><div class="hd">%s</div>%s%s</div>') % (
        PH, img_tag(slot), over, hd_html(slide.get('hd', [])),
        ('<p>%s</p>' % rich(slide['p'])) if slide.get('p') else '', extra)
    return card(tabs, i, inner, last)

def fit_image(src, kind, dst):
    """قص مركزي بنسبة إطار الخانة ثم تكبير لعرض 2200 (بدون تغيير الألوان)."""
    w, h = FRAME.get(kind, FRAME['photo'])
    im = Image.open(src).convert('RGB')
    iw, ih = im.size; ar = w / h
    if iw / ih > ar:
        nw = int(ih * ar); x0 = (iw - nw) // 2; im = im.crop((x0, 0, x0 + nw, ih))
    else:
        nh = int(iw / ar); y0 = 0 if kind == 'cover' else (ih - nh) // 2; im = im.crop((0, y0, iw, y0 + nh))
    if im.width < 2200: im = im.resize((2200, int(im.height * 2200 / im.width)), Image.LANCZOS)
    im.save(dst, quality=95, subsampling=0)

def placeholder(kind, dst, label):
    """مكان صورة مؤقت (للتصميم المبدئي): كحلي بنقاط + «INSERT n»."""
    from PIL import ImageDraw, ImageFont
    w, h = FRAME.get(kind, FRAME['photo']); im = Image.new('RGB', (w * 2, h * 2), (30, 50, 110)); d = ImageDraw.Draw(im)
    for x in range(0, w * 2, 48):
        for y in range(0, h * 2, 48): d.ellipse((x, y, x + 4, y + 4), fill=(70, 100, 170))
    try: f = ImageFont.truetype(str(TPL / 'fonts' / 'GraphikArabic-Black.ttf'), 150)
    except Exception: f = None
    t = 'INSERT %s' % label[1:]; bb = d.textbbox((0, 0), t, font=f)
    d.text(((w * 2 - (bb[2] - bb[0])) / 2, (h * 2 - (bb[3] - bb[1])) / 2), t, fill=(79, 230, 213), font=f)
    im.save(dst, quality=92)

def build(sb, slot_files, workdir, chrome, log=print, outdir='out', draft=False):
    """sb: storyboard dict · slot_files: {slot_id: path|None} · يُرجع قائمة مسارات PNG."""
    work = Path(workdir); b = work / '_src' / 'build'; f = work / '_src' / 'fonts'
    b.mkdir(parents=True, exist_ok=True)
    if not f.exists(): shutil.copytree(TPL / 'fonts', f)
    for f_ in ('style.css', 'logo-white.png', 'qr.svg'): shutil.copy(TPL / f_, b / f_)
    # صور الخانات
    slots = sb['_slots']
    for s in slots:
        dst = b / ('art-%s.jpg' % s['id'])
        src = slot_files.get(s['id'])
        if src and os.path.exists(src): fit_image(src, s['kind'], dst)
        else: placeholder(s['kind'], dst, s['id']); log('تحذير: لا توجد صورة للخانة %s — placeholder' % s['id'])
        s['file'] = 'art-%s.jpg' % s['id']
    slides = sb['slides']
    cta_tab = sb['cta'].get('tab') or {'ar': 'تواصل', 'en': 'Contact'}
    tabs = [s.get('tab', {}) for s in slides] + [cta_tab]
    parts = [cover_html(sb, slots[0])]
    for i, sl in enumerate(slides):
        parts.append(slide_html(sb, i, sl, slots[i + 1], tabs, False))
    parts.append(cta_html(sb, slots[len(slides) + 1], tabs, len(slides)))
    doc = ('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body>%s</body></html>'
           % '\n'.join(parts))
    (b / 'index.html').write_text(doc, encoding='utf-8')
    n = len(parts); full = b / '_full.png'
    chromerun.shot(chrome, ['--hide-scrollbars', '--allow-file-access-from-files',
                    '--force-device-scale-factor=2', '--window-size=1080,%d' % (1080 * n), '--screenshot=' + str(full),
                    '--virtual-time-budget=9000', 'file:///' + str(b / 'index.html').replace('\\', '/')])
    im = Image.open(full).convert('RGB'); band = im.width  # 2160 (مربع)
    out = work / outdir; out.mkdir(exist_ok=True); files = []
    for i in range(n):
        p = out / ('slide-%02d.png' % (i + 1))
        crop = im.crop((0, i * band, im.width, (i + 1) * band))
        for _ in range(8):
            try: crop.save(p, 'PNG'); break
            except OSError: time.sleep(1)
        files.append(str(p))
    imgs = [Image.open(p).convert('RGB') for p in files]
    imgs[0].save(out / 'carousel.pdf', save_all=True, append_images=imgs[1:], resolution=200)
    return files
