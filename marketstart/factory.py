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
VERSION = 'v2.1-fun'


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
    img = Image.new('RGB', (720, 1280), '#17102e')
    d = ImageDraw.Draw(img)
    accent = ['#59e6c6', '#7bb4ff', '#ffca72'][int(key[:2], 16) % 3]
    # Original geometric backgrounds, no third-party footage or music.
    d.ellipse((340, -140, 980, 500), fill='#352058')
    d.ellipse((-180, 930, 330, 1440), fill='#28204c')
    d.text((64, 70), 'BYTE / QUICK BRAIN BREAK', font=font(24, True), fill=accent)
    # Original code-native fictional robot host; expressions change with each scene.
    d.line((360, 130, 360, 165), fill=accent, width=8)
    d.ellipse((345, 108, 375, 138), fill=accent)
    d.rounded_rectangle((235, 165, 485, 335), radius=55, fill='#f3eaff', outline=accent, width=6)
    d.rounded_rectangle((251, 184, 469, 301), radius=38, fill='#241643')
    for x in [302, 411]:
        if index == total-2:
            d.arc((x-22, 213, x+22, 254), 180, 360, fill=accent, width=8)
        else:
            d.ellipse((x-17, 215, x+17, 255), fill=accent)
            d.ellipse((x-5, 219, x+3, 228), fill='white')
    d.arc((335, 247, 390, 281), 0, 180, fill='#ffa4d9', width=6)
    d.ellipse((268, 261, 292, 275), fill='#ffa4d9')
    d.ellipse((422, 261, 446, 275), fill='#ffa4d9')
    label = 'WAIT... WHAT?' if index == 0 else ('SEE YOU NEXT TIME' if index == total-1 else ('THE REVEAL' if index == total-2 else 'YOUR TURN'))
    d.text((64, 380), label, font=font(20, True), fill=accent)
    size = 58 if index == 0 else 43
    face = font(size, True)
    rows = lines_for(d, text, face, 584)
    while (len(rows) > 6 or any(d.textlength(row, font=face) > 584 for row in rows)) and size > 20:
        size -= 2
        face = font(size, True)
        rows = lines_for(d, text, face, 584)
    y = 450
    for row in rows:
        d.text((64, y), row, font=face, fill='#edf4ff')
        y += size + 18
    d.rounded_rectangle((64, 958, 656, 965), radius=3, fill='#25364d')
    d.rounded_rectangle((64, 958, 64 + int(592 * (index+1)/total), 965), radius=3, fill=accent)
    d.text((64, 1000), 'A LITTLE SURPRISE FOR YOUR DAY', font=font(21, True), fill=accent)
    d.text((64, 1048), 'BYTE / fictional AI character', font=font(20), fill='#b0bed2')
    d.text((64, 1090), 'All-ages fun | AI assisted', font=font(17), fill='#8797ae')
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
            durations = [2] + [4]*len(data['scenes']) + [3]
            listing = ''.join(f"file '{i}.png'\nduration {seconds}\n" for i, seconds in enumerate(durations))
            listing += f"file '{len(texts)-1}.png'\n"
            (root / 'frames.txt').write_text(listing)
            duration = sum(durations)
            # Low-volume synthesized chord: original audio, no copyrighted tracks.
            sound = 'sine=frequency=220:sample_rate=44100[a];sine=frequency=330:sample_rate=44100[b];[a][b]amix=inputs=2:duration=longest,volume=0.15'
            args = [executable, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'concat', '-safe', '0', '-i', str(root / 'frames.txt'),
                    '-f', 'lavfi', '-i', sound, '-t', str(duration),
                    '-vf', 'fps=24,fade=t=out:st=' + str(duration-0.3) + ':d=0.3',
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
    topics = {slug: {'hook':hook,'scenes':scenes,'cta':'One tiny brain break. Come back for another.'} for slug,hook,scenes in [('towel', 'What gets wetter while drying?', ['Not a cloud. Not a sponge.', 'You probably used one today.', 'A towel. It dries you... and gets wet.']), ('runner', 'You pass the runner in second place.', ['What place are you in now?', 'First? That is the trap.', 'Second. You took their place, not the lead.']), ('letters', 'Count the F letters. Ready?', ['FINISHED FILES ARE THE RESULT OF YEARS OF SCIENTIFIC STUDY OF PHENOMENA.', 'Count again. Did you include every OF?', 'There are 6. Yes, those little OFs count too.']), ('teeth', 'What has teeth but cannot bite?', ['A tiny dragon? Nice guess.', 'You might keep it near a mirror.', 'A comb. The most polite set of teeth.']), ('calendar', 'Which month has 28 days?', ['February feels like the obvious answer.', 'Read it again: HAS 28 days.', 'All twelve. Some just have a few extra.']), ('keyboard', 'I have keys but no locks.', ['I have space but no room.', 'You can enter, but you cannot go inside.', 'A keyboard. Now the clues click.']), ('light', 'What fills a room but takes no space?', ['You cannot put it in a box.', 'A switch might be your best hint.', 'Light. Bright answer, right?']), ('clock', 'What has hands but cannot clap?', ['It can point without fingers.', 'It is always trying to tell you something.', 'A clock. Terrible at applause.']), ('bottle', 'What has a neck but no head?', ['It never needs a haircut.', 'You may have one in your kitchen.', 'A bottle. Mystery uncorked.']), ('echo', 'I repeat you without knowing your words.', ['No phone. No recording.', 'Try calling out in an empty canyon.', 'An echo. Nature has a repeat button.']), ('siblings', 'Two sisters share the same one brother.', ['How many children are in this family?', 'The brother is shared, not counted twice.', 'Three. Two sisters and one brother.']), ('race', 'What moves forward while staying in place?', ['It can run for hours.', 'Your feet may know this one.', 'A treadmill. All that effort, same address.'])]}
    def topic_script(slug):
        if slug not in topics:
            raise HTTPException(404, 'Unknown entertainment topic')
        return validate_script(topics[slug])

    @app.get('/api/content-factory')
    def inventory():
        return {'renderer': 'ready', 'version': VERSION, 'language': 'en', 'audience': 'international',
                'format': 'MP4 H.264/AAC 720x1280 24fps', 'cadence': '2 posts/day; 3-day rolling queue',
                'publisher': 'Metricool brand 6066678 / no.plan..just.cont',
                'publishing_status': 'Check Metricool for actual pending/published/error status',
                'theme': 'family-friendly riddles, gentle humor, curiosity',
                'custom_url': site_url + '/media/factory/script/{base64url_json}.mp4',
                'script_schema': {'hook': '1-90 chars', 'scenes': '3-5 strings, each 1-130 chars', 'cta': '1-90 chars'},
                'encoding': 'base64url UTF-8 JSON, no padding; keys hook, scenes, cta',
                'posts': [{'slug': slug, 'script': topic_script(slug),
                           'media': site_url + f'/media/factory/topic/{slug}.mp4',
                           'text': v['hook'] + ' Take a tiny brain break with BYTE. AI-assisted original video. #riddle #brainbreak #funfacts'}
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
        return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BYTE — развлекательный контент-завод</title>
        <style>body{{background:#08101e;color:#edf4ff;font:17px system-ui;margin:auto;padding:30px;max-width:1100px}}h1{{font-size:42px}}a{{color:#59e6c6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px}}article{{background:#13202f;border-radius:20px;padding:20px}}video{{width:100%;max-height:420px}}p{{line-height:1.6;color:#b0bed2}}</style>
        <h1>Контент-завод TikTok</h1><p>@no.plan..just.cont · зарубежная аудитория · английский язык</p>
        <p>BYTE — вымышленный мультяшный ИИ-ведущий. Загадки, добрый юмор и неожиданные развязки без 18+. Вертикальные MP4 с титрами и оригинальной фоновой музыкой. План: два ролика в день, очередь на три дня. Ежедневная автоматизация создаёт новые сценарии и отправляет их в Metricool.</p>
        <p>Фактические статусы публикаций: <a href="https://app.metricool.com/">открыть Metricool</a>. Здесь доступен генератор и предпросмотр; число просмотров и опубликованных роликов не моделируется.</p>
        <p><a href="/api/content-factory">API генератора</a></p><div class="grid">{cards}</div></html>'''
