"""Reproducible TikTok video renderer. Publishing lives in Metricool, not here."""
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from PIL import Image, ImageDraw, ImageFont

CACHE = Path(tempfile.gettempdir()) / 'marketstart-video-v1'
LOCK = threading.BoundedSemaphore(1)
MAX_CACHE_FILES = 40
VERSION = 'v1'


def validate_script(data):
    if not isinstance(data, dict) or set(data) - {'hook', 'scenes', 'cta'}:
        raise ValueError('Use hook, scenes and cta only')
    for name, limit in [('hook', 90), ('cta', 90)]:
        value = data.get(name)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise ValueError(f'{name} must contain 1-{limit} characters')
    scenes = data.get('scenes')
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 5:
        raise ValueError('Use 3-5 scenes')
    if any(not isinstance(s, str) or not 1 <= len(s.strip()) <= 130 for s in scenes):
        raise ValueError('Each scene must contain 1-130 characters')
    if any(ord(c) < 32 for s in [data['hook'], *scenes, data['cta']] for c in s):
        raise ValueError('Control characters are not allowed')
    return {'hook': data['hook'].strip(), 'scenes': [s.strip() for s in scenes], 'cta': data['cta'].strip()}


def encode_script(data):
    raw = json.dumps(validate_script(data), separators=(',', ':'), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode_script(token):
    if len(token) > 2200 or not re.fullmatch(r'[A-Za-z0-9_-]+', token):
        raise ValueError('Invalid script token')
    raw = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
    return validate_script(json.loads(raw))


def font(size, bold=False):
    paths = ['/usr/share/fonts/truetype/dejavu/DejaVuSans' + ('-Bold' if bold else '') + '.ttf',
             '/usr/share/fonts/truetype/liberation2/LiberationSans' + ('-Bold' if bold else '-Regular') + '.ttf']
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def lines_for(draw, text, face, width):
    lines, line = [], ''
    for word in text.split():
        candidate = (line + ' ' + word).strip()
        if draw.textlength(candidate, font=face) > width:
            if line:
                lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def card(text, index, total, key):
    img = Image.new('RGB', (720, 1280), '#08101e')
    d = ImageDraw.Draw(img)
    accent = ['#59e6c6', '#7bb4ff', '#ffca72'][int(key[:2], 16) % 3]
    # Original geometric backgrounds, no third-party footage or music.
    d.ellipse((340, -140, 980, 500), fill='#112737')
    d.ellipse((-180, 930, 330, 1440), fill='#13202f')
    d.text((64, 155), 'MARKETSTART AI', font=font(24, True), fill=accent)
    label = 'THE IDEA' if index == 0 else ('YOUR NEXT STEP' if index == total-1 else f'STEP {index}')
    d.text((64, 260), label, font=font(20, True), fill=accent)
    size = 58 if index == 0 else 43
    face = font(size, True)
    rows = lines_for(d, text, face, 584)
    while (len(rows) > 7 or any(d.textlength(row, font=face) > 584 for row in rows)) and size > 20:
        size -= 2
        face = font(size, True)
        rows = lines_for(d, text, face, 584)
    y = 360
    for row in rows:
        d.text((64, y), row, font=face, fill='#edf4ff')
        y += size + 18
    d.rounded_rectangle((64, 958, 656, 965), radius=3, fill='#25364d')
    d.rounded_rectangle((64, 958, 64 + int(592 * (index+1)/total), 965), radius=3, fill=accent)
    d.text((64, 1000), 'SAVE THIS FOR YOUR NEXT LAUNCH', font=font(21, True), fill=accent)
    d.text((64, 1048), 'Free framework: MarketStart AI', font=font(20), fill='#b0bed2')
    d.text((64, 1090), 'Educational content | AI assisted', font=font(17), fill='#8797ae')
    return img


def render_video(data):
    payload = json.dumps(validate_script(data), sort_keys=True).encode()
    key = hashlib.sha256(VERSION.encode() + payload).hexdigest()
    CACHE.mkdir(exist_ok=True)
    target = CACHE / (key + '.mp4')
    if target.exists():
        return target
    if not LOCK.acquire(timeout=50):
        raise HTTPException(503, 'Renderer busy; try again later', headers={'Retry-After': '60'})
    try:
        if target.exists():
            return target
        import imageio_ffmpeg
        executable = os.getenv('FACTORY_FFMPEG') or imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix='marketstart-render-') as tmp:
            root = Path(tmp)
            texts = [data['hook'], *data['scenes'], data['cta']]
            for i, text in enumerate(texts):
                card(text, i, len(texts), key).save(root / f'{i}.png')
            durations = [3] + [5]*len(data['scenes']) + [4]
            listing = ''.join(f"file '{i}.png'\nduration {seconds}\n" for i, seconds in enumerate(durations))
            listing += f"file '{len(texts)-1}.png'\n"
            (root / 'frames.txt').write_text(listing)
            duration = sum(durations)
            # Low-volume synthesized chord: original audio, no copyrighted tracks.
            sound = 'sine=frequency=220:sample_rate=44100[a];sine=frequency=330:sample_rate=44100[b];[a][b]amix=inputs=2:duration=longest,volume=0.15'
            args = [executable, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'concat', '-safe', '0', '-i', str(root / 'frames.txt'),
                    '-f', 'lavfi', '-i', sound, '-t', str(duration),
                    '-vf', 'fps=24,fade=t=in:st=0:d=0.3,fade=t=out:st=' + str(duration-0.3) + ':d=0.3',
                    '-c:v', 'libx264', '-threads', '1', '-preset', 'veryfast', '-crf', '25',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                    '-movflags', '+faststart', str(root / 'video.mp4')]
            try:
                subprocess.run(args, check=True, timeout=90, capture_output=True)
            except (subprocess.SubprocessError, OSError) as exc:
                raise HTTPException(503, 'Video rendering failed') from exc
            shutil.copyfile(root / 'video.mp4', CACHE / (key + '.tmp'))
            os.replace(CACHE / (key + '.tmp'), target)
        files = sorted(CACHE.glob('*.mp4'), key=lambda p: p.stat().st_mtime)
        for old in files[:-MAX_CACHE_FILES]:
            if old != target:
                old.unlink(missing_ok=True)
        return target
    finally:
        LOCK.release()


def install_factory(app, topics, site_url):
    def topic_script(slug):
        data = topics.get(slug)
        if not data:
            raise HTTPException(404, 'Unknown topic')
        scene_bank = {
            'margin': ['Selling price is only the starting point.', 'Subtract product cost, platform fees and fulfillment.', 'Budget for returns, ads and taxes before you scale.'],
            'inventory': ['Order the smallest useful test batch.', 'Measure conversion, returns and margin per order.', 'Reorder only after real demand supports the decision.'],
            'launch': ['Validate demand before buying stock.', 'Calculate costs and prepare a clear product listing.', 'Launch a small test. Measure results before scaling.'],
            'returns': ['A returned order still creates handling costs.', 'Estimate return shipping and unsellable inventory.', 'Include an expected return allowance in your price.'],
            'conversion': ['Show the product clearly in the first image.', 'Explain its use, dimensions and delivery promise.', 'Improve the listing before buying more traffic.'],
            'pricing': ['Compare the whole offer, not only its price.', 'Delivery speed, product clarity and trust affect buying decisions.', 'Test price changes against contribution margin per order.'],
            'stock': ['Track daily sell-through and remaining inventory.', 'Add supplier lead time to your reorder plan.', 'Place the next order before stock becomes critical.'],
            'ads': ['Calculate contribution margin before advertising.', 'Use it to estimate your break-even acquisition cost.', 'Scale only when actual results support the economics.'],
            'supplier': ['The supplier quote leaves out part of the cost.', 'Add freight, inspection, duties and packaging.', 'Compare landed cost together with reliability and defect rates.'],
            'reviews': ['Clear instructions prevent avoidable frustration.', 'Reliable quality and packaging improve the experience.', 'Earn honest reviews. Never buy or fabricate them.'],
            'cashflow': ['You pay for inventory before many sales are collected.', 'Forecast supplier payments and marketplace payout delays.', 'Keep a cash reserve for operating costs and taxes.'],
            'testing': ['Choose one question before running a test.', 'Change one major variable: image, price or title.', 'Compare similar periods and enough orders before deciding.'],
        }
        return validate_script({'hook': data['hook'], 'scenes': scene_bank[slug], 'cta': 'Save this. Free framework at MarketStart AI.'})

    @app.get('/api/content-factory')
    def inventory():
        return {'renderer': 'ready', 'version': VERSION, 'language': 'en', 'audience': 'international',
                'format': 'MP4 H.264/AAC 720x1280 24fps', 'cadence': '2 posts/day; 3-day rolling queue',
                'publisher': 'Metricool brand 6066678 / no.plan..just.cont',
                'publishing_status': 'Check Metricool for actual pending/published/error status',
                'landing': site_url + '/global',
                'custom_url': site_url + '/media/factory/script/{base64url_json}.mp4',
                'script_schema': {'hook': '1-90 chars', 'scenes': '3-5 strings, each 1-130 chars', 'cta': '1-90 chars'},
                'encoding': 'base64url UTF-8 JSON, no padding; keys hook, scenes, cta',
                'posts': [{'slug': slug, 'script': topic_script(slug),
                           'media': site_url + f'/media/factory/topic/{slug}.mp4',
                           'text': v['hook'] + ' ' + v['body'] + ' ' + v['cta'] + ' #ecommerce #marketplace #sellertips'}
                          for slug, v in topics.items()]}

    @app.api_route('/media/factory/topic/{slug}.mp4', methods=['GET', 'HEAD'])
    def topic_video(slug: str, request: Request):
        return FileResponse(render_video(topic_script(slug)), media_type='video/mp4',
                            headers={'Cache-Control': 'public, max-age=604800'})

    @app.api_route('/media/factory/script/{token}.mp4', methods=['GET', 'HEAD'])
    def custom_video(token: str, request: Request):
        try:
            script = decode_script(token)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise HTTPException(400, 'Invalid video script') from exc
        return FileResponse(render_video(script), media_type='video/mp4',
                            headers={'Cache-Control': 'public, max-age=604800'})

    @app.get('/content-factory', response_class=HTMLResponse)
    def dashboard():
        cards = ''.join(f'<article><h3>{html.escape(v["hook"])}</h3><video controls preload="none" src="/media/factory/topic/{slug}.mp4"></video></article>' for slug, v in topics.items())
        return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Контент-завод — MarketStart</title>
        <style>body{{background:#08101e;color:#edf4ff;font:17px system-ui;margin:auto;padding:30px;max-width:1100px}}h1{{font-size:42px}}a{{color:#59e6c6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px}}article{{background:#13202f;border-radius:20px;padding:20px}}video{{width:100%;max-height:420px}}p{{line-height:1.6;color:#b0bed2}}</style>
        <h1>Контент-завод TikTok</h1><p>@no.plan..just.cont · зарубежная аудитория · английский язык</p>
        <p>Генератор: вертикальные MP4 с титрами и оригинальной фоновой музыкой. План: два ролика в день, очередь на три дня. Ежедневная автоматизация создаёт новые сценарии и отправляет их в Metricool.</p>
        <p>Фактические статусы публикаций: <a href="https://app.metricool.com/">открыть Metricool</a>. Здесь доступен генератор и предпросмотр; число просмотров и опубликованных роликов не моделируется.</p>
        <p><a href="/global">Страница для аудитории</a> · <a href="/api/content-factory">API генератора</a></p><div class="grid">{cards}</div></html>'''
