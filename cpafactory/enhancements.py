import os, re, json, html, urllib.request, urllib.parse, tempfile, subprocess, shutil, threading, hashlib
from fastapi import Header, HTTPException
from fastapi.responses import Response

import app as core
from PIL import Image

MEDIA_KEYS = ("image_url","image_url2","video_url","video_url2")

def fetch_media(url):
    out={k:"" for k in MEDIA_KEYS}
    if not url or not str(url).startswith(("http://","https://")):
        return out
    try:
        req=urllib.request.Request(str(url),headers={"User-Agent":"Mozilla/5.0 CPAFactory/1.0"})
        with urllib.request.urlopen(req,timeout=6) as r:
            raw=r.read(1200000).decode("utf-8","ignore")
    except Exception:
        return out
    def meta(prop):
        pats=[
            r'<meta[^>]+(?:property|name)=["\']'+re.escape(prop)+r'["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']'+re.escape(prop)+r'["\']'
        ]
        for p in pats:
            m=re.search(p,raw,re.I)
            if m: return html.unescape(m.group(1)).strip()
        return ""
    imgs=[]
    for p in ("og:image","twitter:image","image"):
        u=meta(p)
        if u and u not in imgs: imgs.append(urllib.parse.urljoin(str(url),u))
    vids=[]
    for p in ("og:video","og:video:url","twitter:player:stream"):
        u=meta(p)
        if u and u not in vids: vids.append(urllib.parse.urljoin(str(url),u))
    for m in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\']',raw,re.I):
        u=urllib.parse.urljoin(str(url),html.unescape(m.group(1)))
        if any(u.lower().split("?")[0].endswith(x) for x in (".mp4",".webm",".mov",".m4v")) and u not in vids:
            vids.append(u)
    out["image_url"]=imgs[0] if imgs else ""
    out["image_url2"]=imgs[1] if len(imgs)>1 else ""
    out["video_url"]=vids[0] if vids else ""
    out["video_url2"]=vids[1] if len(vids)>1 else ""
    return out

def migrate():
    with core.db() as c:
        stmts=[
            "alter table offers add column video_url text",
            "alter table offers add column video_url2 text",
            "alter table offers add column demand_count real default 0",
            "alter table offers add column demand_checked_at text",
            "alter table offers add column yandex_promise real default 0"
        ]
        for s in stmts:
            try: c.execute(s)
            except Exception: pass
    print("CPA_ENHANCEMENTS_MIGRATION_OK",flush=True)

def enrich_existing(limit=100):
    try:
        with core.db() as c:
            rows=c.execute("select id,site_url,image_url,image_url2,video_url,video_url2 from offers where active=true order by id desc limit %s",(max(1,min(int(limit),200)),)).fetchall()
            changed=0
            for r in rows:
                if not r["site_url"]: continue
                if r["image_url"] and r["video_url"]: continue
                m=fetch_media(r["site_url"])
                vals={k:(r[k] or m.get(k,"")) for k in MEDIA_KEYS}
                if any(vals[k] != (r[k] or "") for k in MEDIA_KEYS):
                    c.execute("update offers set image_url=%s,image_url2=%s,video_url=%s,video_url2=%s where id=%s",
                              (vals["image_url"],vals["image_url2"],vals["video_url"],vals["video_url2"],r["id"]))
                    changed+=1
            print("CPA_MEDIA_ENRICH",json.dumps({"status":"ok","checked":len(rows),"changed":changed},ensure_ascii=False),flush=True)
    except Exception as e:
        print("CPA_MEDIA_ENRICH_ERROR",type(e).__name__,str(e),flush=True)

_WORDSTAT_DISABLED=False
_WORDSTAT_DISABLED_REASON=""

def wordstat_count(phrase):
    global _WORDSTAT_DISABLED, _WORDSTAT_DISABLED_REASON
    if _WORDSTAT_DISABLED:
        return 0
    token=os.getenv("YANDEX_SEARCH_API_KEY","").strip()
    folder_id=os.getenv("YANDEX_SEARCH_FOLDER_ID","").strip()
    if not token or not phrase or not folder_id:
        return 0
    try:
        regions=[x.strip() for x in os.getenv("YANDEX_WORDSTAT_REGIONS","").split(",") if x.strip()]
        devices=[x.strip() for x in os.getenv("YANDEX_WORDSTAT_DEVICES","DEVICE_PHONE").split(",") if x.strip()]
        body={"phrase":str(phrase)[:300],"numPhrases":50,"folderId":folder_id}
        if regions: body["regions"]=regions
        if devices: body["devices"]=devices
        req=urllib.request.Request(
            "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests",
            data=json.dumps(body,ensure_ascii=False).encode(),
            headers={"Authorization":f"Api-Key {token}","Content-Type":"application/json"},
            method="POST")
        with urllib.request.urlopen(req,timeout=20) as r:
            data=json.loads(r.read().decode())
        rows=data.get("results") or []
        target=str(phrase).strip().lower()
        exact=[int(x.get("count") or 0) for x in rows if str(x.get("phrase","")).strip().lower()==target]
        return max(exact or [max([int(x.get("count") or 0) for x in rows] or [int(data.get("totalCount") or 0)])])
    except Exception as e:
        msg=f"{type(e).__name__}: {e}"
        if isinstance(e, urllib.error.HTTPError) and getattr(e,"code",0) in (401,403):
            _WORDSTAT_DISABLED=True
            _WORDSTAT_DISABLED_REASON=msg
            print("WORDSTAT_DISABLED",msg,flush=True)
        else:
            print("WORDSTAT_ERROR",msg,flush=True)
        return 0

def refresh_demand(limit=30):
    if not os.getenv("YANDEX_SEARCH_API_KEY","").strip() or not os.getenv("YANDEX_SEARCH_FOLDER_ID","").strip():
        return {"status":"not_configured","checked":0}
    with core.db() as c:
        rows=c.execute("select id,name from offers where active=true order by id desc limit %s",(max(1,min(limit,100)),)).fetchall()
        for r in rows:
            count=wordstat_count(r["name"])
            c.execute("update offers set demand_count=%s,demand_checked_at=current_timestamp where id=%s",(count,r["id"]))
    return {"status":"ok","checked":len(rows)}

def yandex_link(market_url):
    token=os.getenv("YANDEX_MARKET_OAUTH","").strip()
    place=os.getenv("YANDEX_MARKET_PLACE_ID","").strip()
    clid=os.getenv("YANDEX_MARKET_CLID","").strip()
    if not token or (not place and not clid): return None
    p={"url":market_url,"format":"json","vid":"cf_auto"}
    if place: p["place_id"]=place
    else: p["clid"]=clid
    url="https://api.content.market.yandex.ru/v3/affiliate/partner/link/create?"+urllib.parse.urlencode(p)
    req=urllib.request.Request(url,headers={"Authorization":f"OAuth {token}","Accept":"application/json","User-Agent":"CPAFactory/1.0"})
    with urllib.request.urlopen(req,timeout=20) as r: data=json.loads(r.read().decode())
    if data.get("status")!="OK" or not data.get("link",{}).get("url"):
        raise RuntimeError(str(data))
    return data

@core.app.get("/api/cpa/import/yandex")
def import_yandex(x_admin_token: str | None = Header(default=None)):
    core.require_admin(x_admin_token)
    raw=os.getenv("YANDEX_MARKET_URLS","").strip()
    if not raw:
        return {"status":"not_configured","message":"Задайте YANDEX_MARKET_URLS — ссылки на карточки товаров Яндекс Маркета."}
    urls=[x.strip() for x in re.split(r"[\n,;]+",raw) if x.strip()]
    added=updated=0
    with core.db() as c:
        for market_url in urls[:100]:
            if "market.yandex.ru" not in market_url: continue
            try:
                data=yandex_link(market_url)
                link=data["link"]; media=fetch_media(market_url)
                title=link.get("title") or market_url
                ext=hashlib.sha1(market_url.encode()).hexdigest()[:24]
                img=link.get("productPhoto") or media["image_url"]
                vals=(title,"Яндекс Маркет",float(data.get("price") or 0),float(data.get("promise") or 0),
                      link["url"],json.dumps({"source":"yandex_market","stock":data.get("stockAmount")},ensure_ascii=False),
                      ext,market_url,img,media["image_url2"],media["video_url"],media["video_url2"],float(data.get("promise") or 0))
                ex=c.execute("select id from offers where source='yandex_market' and external_id=%s",(ext,)).fetchone()
                if ex:
                    c.execute("update offers set name=%s,merchant=%s,price=%s,commission=%s,tracking_url=%s,traffic_rules=%s,active=true,site_url=%s,image_url=%s,image_url2=%s,video_url=%s,video_url2=%s,yandex_promise=%s where id=%s",vals+(ex["id"],))
                    updated+=1
                else:
                    c.execute("insert into offers(name,merchant,price,commission,tracking_url,traffic_rules,active,source,external_id,site_url,image_url,image_url2,video_url,video_url2,yandex_promise) values(%s,%s,%s,%s,%s,%s,true,'yandex_market',%s,%s,%s,%s,%s,%s,%s)",vals)
                    added+=1
            except Exception as e:
                print("YANDEX_IMPORT_ERROR",type(e).__name__,str(e),flush=True)
    return {"status":"ok","source":"yandex_market","received":len(urls),"added":added,"updated":updated}

@core.app.get("/api/cpa/refresh-demand")
def refresh_demand_endpoint(x_admin_token: str | None = Header(default=None)):
    core.require_admin(x_admin_token)
    return refresh_demand(30)

# Pipeline ranking: demand is the primary signal, commercial metrics and seller media are secondary.
def demand_top(limit=10):
    with core.db() as c:
        rows=c.execute("select o.*, count(e.id) clicks from offers o left join click_events e on e.offer_id=o.id where o.active=true group by o.id").fetchall()
    out=[]
    for r in rows:
        demand=float(r["demand_count"] or 0)
        epc=float(r["epc"] or 0); cr=float(r["cr"] or 0); rating=float(r["rating"] or 0)
        clicks=int(r["clicks"] or 0); promise=float(r["yandex_promise"] or 0)
        media=1 if (r["video_url"] or r["image_url"]) else 0
        score=(__import__("math").log1p(max(demand,0))*0.72+
               __import__("math").log1p(max(epc,0))*0.10+
               min(max(cr,0),100)*0.06+
               min(max(rating,0),5)*0.02+
               min(clicks,1000)*0.001+
               min(promise/1000,1)*0.02+
               media*0.08)
        x=dict(r); x["score"]=round(score,4); out.append(x)
    out.sort(key=lambda x:(x["score"],float(x.get("demand_count") or 0),int(x.get("id") or 0)),reverse=True)
    return out[:max(1,min(limit,50))]

_original_pipeline=core._pipeline_run
def pipeline_with_demand():
    try:
        # Keep the commercial pipeline bounded. Seller-page media enrichment is
        # a separate worker; doing up to 100 HTTP fetches inside every pipeline
        # cycle caused the worker to run for minutes and blocked content creation.
        refresh_demand(30)
    except Exception as e:
        print("CPA_PREP_ERROR",type(e).__name__,str(e),flush=True)
    # The original pipeline uses the module-global cpa_top symbol.
    old=core.cpa_top
    core.cpa_top=demand_top
    try:
        return _original_pipeline()
    finally:
        core.cpa_top=old

core._pipeline_run=pipeline_with_demand

_LAST_PREVIEW_VIDEO = {"path":"", "tmp":"", "content_id":0}
_MP4_SELFTEST_LOCK = threading.Lock()

def mp4_selftest():
    global _LAST_PREVIEW_VIDEO
    if not _MP4_SELFTEST_LOCK.acquire(blocking=False):
        result={"status":"busy"}
        print("MP4_PRODUCTION_SELFTEST",json.dumps(result,ensure_ascii=False),flush=True)
        return result
    try:
        with core.db() as c:
            row=c.execute("select * from content order by id desc limit 1").fetchone()
            if not row: return {"status":"no_content"}
            offer_id=row["offer_id"] if "offer_id" in row.keys() else None
            offer=c.execute("select * from offers where id=%s",(offer_id,)).fetchone() if offer_id else c.execute("select * from offers order by id desc limit 1").fetchone()
        row=dict(row); offer=dict(offer) if offer else {}
        old_tmp=_LAST_PREVIEW_VIDEO.get("tmp")
        if old_tmp: shutil.rmtree(old_tmp,ignore_errors=True)
        path,tmp=core._make_mp4(row["id"],row,offer)
        size=os.path.getsize(path)
        _LAST_PREVIEW_VIDEO={"path":path,"tmp":tmp,"content_id":int(row["id"])}
        # Final container-level validation: decode + verify that the finished
        # MP4 really contains both video and audio streams.
        ff=_ffmpeg_exe()
        if not ff:
            raise RuntimeError("ffmpeg недоступен для финальной проверки MP4")
        check=subprocess.run([ff,"-v","error","-i",path,"-f","null","-"],
                             capture_output=True,text=True,timeout=180)
        if check.returncode!=0:
            raise RuntimeError("MP4 decode failed: "+check.stderr[-1200:])
        probe=subprocess.run([ff,"-v","error","-show_entries","stream=codec_type,codec_name,width,height,r_frame_rate","-of","json",path],capture_output=True,text=True,timeout=30)
        if probe.returncode!=0:
            raise RuntimeError("MP4 probe failed: "+probe.stderr[-800:])
        streams=json.loads(probe.stdout or "{}").get("streams",[])
        has_video=any(s.get("codec_type")=="video" for s in streams)
        has_audio=any(s.get("codec_type")=="audio" for s in streams)
        if not has_video or not has_audio:
            raise RuntimeError(f"MP4 streams invalid: video={has_video}, audio={has_audio}")
        print("MP4_DECODE_SELFTEST",json.dumps({"status":"ok","content_id":row["id"],"bytes":size,"video":has_video,"audio":has_audio,"streams":streams},ensure_ascii=False),flush=True)
        print("MP4_PRODUCTION_SELFTEST",json.dumps(result,ensure_ascii=False),flush=True)
        print("MP4_PREVIEW_READY",json.dumps({"content_id":row["id"],"bytes":size,"url":"/api/preview-video"},ensure_ascii=False),flush=True)
        return result
    except Exception as e:
        result={"status":"error","error":f"{type(e).__name__}: {e}"}
        print("MP4_PRODUCTION_SELFTEST",json.dumps(result,ensure_ascii=False),flush=True)
        return result
    finally:
        _MP4_SELFTEST_LOCK.release()

@core.app.get("/api/preview-video")
def preview_video():
    path=_LAST_PREVIEW_VIDEO.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(404,"Готового preview-видео пока нет")
    return core.FileResponse(path,media_type="video/mp4",filename=f"cpafactory_preview_{_LAST_PREVIEW_VIDEO.get('content_id','video')}.mp4",content_disposition_type="inline")

@core.app.get("/api/preview-video/ensure")
def ensure_preview_video():
    """Deterministic production-preview trigger. Never blocks the HTTP request."""
    global _BOOT_STARTED
    preview=_LAST_PREVIEW_VIDEO.get("path")
    if preview and os.path.exists(preview):
        return {"status":"ready","url":"/api/preview-video","content_id":_LAST_PREVIEW_VIDEO.get("content_id")}
    with _BOOT_LOCK:
        running=_BOOT_STARTED
        if not running:
            _BOOT_STARTED=True
            threading.Thread(target=_deep_boot,daemon=True,name="cpa-preview-ensure").start()
    return {"status":"building" if running or _BOOT_STARTED else "queued","status_url":"/api/preview-video/status"}

@core.app.get("/api/preview-video/status")
def preview_video_status():
    path=_LAST_PREVIEW_VIDEO.get("path")
    if path and os.path.exists(path):
        return {"status":"ready","content_id":_LAST_PREVIEW_VIDEO.get("content_id"),"video_url":"/api/preview-video"}
    return {"status":"not_ready"}

# Production TTS: male Russian neural voice, news-style pacing.
def _edge_tts_audio(text, out_path):
    text=str(text or "").strip()
    if not text: raise ValueError("empty TTS text")
    cli=shutil.which("edge-tts")
    if not cli: raise RuntimeError("edge-tts executable not installed")
    cmd=[cli,"--voice","ru-RU-DmitryNeural","--rate","+7%","--pitch","-1Hz","--text",text,"--write-media",out_path]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=45)
    if not os.path.exists(out_path) or os.path.getsize(out_path)<1000: raise RuntimeError("no usable TTS audio")
    return out_path

_PIPER_VOICE = None
_PIPER_VOICE_LOCK = threading.Lock()

def _piper_audio(text,out_path):
    global _PIPER_VOICE
    import wave
    from piper import PiperVoice, SynthesisConfig
    voice_dir=os.path.join(tempfile.gettempdir(),"cpafactory_piper_voices")
    os.makedirs(voice_dir,exist_ok=True)
    model=os.path.join(voice_dir,"ru_RU-ruslan-medium.onnx")
    model_json=model+".json"
    if not (os.path.exists(model) and os.path.exists(model_json)):
        dl=subprocess.run(
            [__import__("sys").executable,"-m","piper.download_voices",
             "--data-dir",voice_dir,"ru_RU-ruslan-medium"],
            capture_output=True,text=True,timeout=120
        )
        if dl.returncode!=0:
            raise RuntimeError("Piper voice download failed: "+dl.stderr[-800:])
    with _PIPER_VOICE_LOCK:
        if _PIPER_VOICE is None:
            _PIPER_VOICE=PiperVoice.load(model)
    wav_path=out_path+".wav"
    syn=SynthesisConfig(length_scale=1.12)
    with wave.open(wav_path,"wb") as wf:
        _PIPER_VOICE.synthesize_wav(str(text or ""),wf,syn_config=syn)
    ff=_ffmpeg_exe()
    if not ff: raise RuntimeError("ffmpeg недоступен")
    subprocess.run([ff,"-y","-i",wav_path,"-codec:a","libmp3lame","-b:a","128k",out_path],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
    try: os.remove(wav_path)
    except Exception: pass
    if not os.path.exists(out_path) or os.path.getsize(out_path)<1000:
        raise RuntimeError("Piper не создал MP3")
    return out_path

def production_tts_audio(text,out_path):
    try:
        result=_piper_audio(text,out_path)
        print("PIPER_TTS_OK",json.dumps({"voice":"ru_RU-ruslan-medium","bytes":os.path.getsize(result)},ensure_ascii=False),flush=True)
        return result
    except Exception as ex:
        print("PIPER_TTS_FALLBACK",type(ex).__name__,str(ex),flush=True)
    try:
        return _edge_tts_audio(text,out_path)
    except Exception as ex:
        print("EDGE_TTS_FALLBACK",type(ex).__name__,str(ex),flush=True)
        return core._tts_audio(text,out_path)

# Read direct seller video fields from XML when present.
_original_gdeslon_parse=core._gdeslon_parse_xml
def parse_gdeslon_with_video(raw):
    items=_original_gdeslon_parse(raw)
    try:
        import xml.etree.ElementTree as ET
        root=ET.fromstring(raw); by_id={}
        for n in root.iter():
            if n.tag.split("}")[-1].lower() not in ("offer","product"): continue
            attrs=dict(n.attrib); oid=attrs.get("id") or attrs.get("offer_id")
            if not oid: continue
            vids=[]
            for ch in n.iter():
                t=ch.tag.split("}")[-1].lower(); v=(ch.text or "").strip()
                if "video" in t and v.startswith(("http://","https://")): vids.append(v)
            if vids: by_id[str(oid)]=vids[:2]
        for x in items:
            vids=by_id.get(str(x.get("id")),[])
            x["video_url"]=vids[0] if vids else ""
            x["video_url2"]=vids[1] if len(vids)>1 else ""
    except Exception as e:
        print("GDESLON_VIDEO_PARSE_ERROR",type(e).__name__,str(e),flush=True)
    return items
core._gdeslon_parse_xml=parse_gdeslon_with_video

_original_gdeslon_import=core.cpa_import_gdeslon
def import_gdeslon_with_video(x_admin_token: str | None = Header(default=None)):
    result=_original_gdeslon_import(x_admin_token)
    try:
        with core.db() as c:
            rows=c.execute("select id,site_url,image_url,image_url2,video_url,video_url2 from offers where active=true and source='gdeslon' order by id desc limit 100").fetchall()
            changed=0
            for r in rows:
                if not r["site_url"]: continue
                m=fetch_media(str(r["site_url"]))
                vals={k:(r[k] or m.get(k,"")) for k in MEDIA_KEYS}
                if any(vals[k] != (r[k] or "") for k in MEDIA_KEYS):
                    c.execute("update offers set image_url=%s,image_url2=%s,video_url=%s,video_url2=%s where id=%s",(vals["image_url"],vals["image_url2"],vals["video_url"],vals["video_url2"],r["id"]))
                    changed+=1
            result["media_checked"]=len(rows); result["media_changed"]=changed
    except Exception as e: result["media_error"]=f"{type(e).__name__}: {e}"
    return result
core.cpa_import_gdeslon=import_gdeslon_with_video

def _download(url,path,limit=30*1024*1024):
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 CPAFactory/1.0"})
        with urllib.request.urlopen(req,timeout=25) as r: data=r.read(limit)
        with open(path,"wb") as f: f.write(data)
        return path
    except Exception:
        return None

def seller_video(offer,tmp):
    urls=[str(offer.get(k)) for k in ("video_url","video_url2") if offer.get(k)]
    if not urls and offer.get("site_url"):
        m=fetch_media(str(offer["site_url"])); urls=[m["video_url"],m["video_url2"]]
    for i,u in enumerate([x for x in urls if x][:2]):
        ext=".mp4"; low=u.lower().split("?")[0]
        for x in (".webm",".mov",".m4v"):
            if low.endswith(x): ext=x
        p=os.path.join(tmp,f"seller_{i}{ext}")
        if _download(u,p): return p
    return None

_original_make=core._make_mp4
def _ffmpeg_exe():
    ff=shutil.which("ffmpeg")
    if ff: return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def _probe_duration(ff,path,default=10.0):
    try:
        p=subprocess.run([ff,"-i",path],capture_output=True,text=True,timeout=20)
        m=re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)",p.stderr)
        return float(m.group(1))*3600+float(m.group(2))*60+float(m.group(3)) if m else default
    except Exception:
        return default

def _video_progress(percent, stage):
    cb=getattr(core, '_VIDEO_PROGRESS_CALLBACK', None)
    if cb:
        try: cb(percent, stage)
        except Exception: pass

def _clean_image_video(content_id,row,offer,tmp,ff):
    # Render Free-safe production path: one image + one narration + one FFmpeg pass.
    # This avoids per-scene H.264 encodes, which can exceed the free CPU budget.
    _video_progress(10, 'Подготовка медиа товара')
    imgs=[offer.get('image_url'),offer.get('image_url2')]
    src=None
    for u in [x for x in imgs if x]:
        p=os.path.join(tmp,'product.jpg')
        if _download(str(u),p,12*1024*1024):
            src=p; break
    if not src:
        src=os.path.join(tmp,'placeholder.png')
        from PIL import Image, ImageDraw
        im=Image.new('RGB',(1080,1920),(24,24,28))
        d=ImageDraw.Draw(im)
        d.text((90,820),'CPA Factory',fill=(245,245,245))
        d.text((90,900),'Товар из партнёрской сети',fill=(190,190,190))
        im.save(src,'PNG')
    _video_progress(20, 'Озвучка')
    pack=core.build_content_pack(row,offer)
    scenes=pack.get('scenes') or []
    narration=' '.join(core._video_text(sc.get('text','')) for sc in scenes if sc.get('text'))
    if not narration:
        narration=core._video_text(str(row.get('script','')))
    audio=os.path.join(tmp,'narration.mp3')
    production_tts_audio(narration,audio)
    # Render Free has a hard CPU budget. This is a static-image short, so
    # encode only a few video frames per second while keeping the requested
    # 1080x1920 H.264/AAC container. Cap narration to 30s to make production
    # deterministic instead of allowing long TTS jobs to time out.
    dur=max(5.0,min(30.0,_probe_duration(ff,audio,12.0)+0.35))
    out=os.path.join(tmp,f'content_{content_id}.mp4')
    _video_progress(45, 'Сборка MP4')
    vf='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p'
    cmd=[ff,'-y','-loop','1','-i',src,'-i',audio,'-t',f'{dur:.2f}','-vf',vf,'-r','3',
         '-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','ultrafast','-tune','stillimage',
         '-crf','35','-pix_fmt','yuv420p','-g','6','-keyint_min','6','-sc_threshold','0',
         '-c:a','aac','-b:a','96k','-ar','44100','-shortest','-movflags','+faststart',out]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=75)
    _video_progress(96, 'Проверка готового файла')
    return out,tmp
def make_mp4_seller_first(content_id,row,offer):
    if hasattr(row,"keys") and not isinstance(row,dict): row=dict(row)
    if hasattr(offer,"keys") and not isinstance(offer,dict): offer=dict(offer)
    tmp=tempfile.mkdtemp(prefix="cfvideo_")
    try:
        ff=_ffmpeg_exe()
        if not ff: return _original_make(content_id,row,offer)
        # On Render Free, seller-video transcoding is too expensive and has
        # repeatedly caused 45-120s FFmpeg timeouts. Use the resource-safe
        # product-image path for deterministic production generation.
        _video_progress(8, 'Подготовка медиа товара')
        out,tmp2=_clean_image_video(content_id,row,offer,tmp,ff)

        print("VIDEO_BUILD",json.dumps({"content_id":content_id,"seller_video":False,"resolution":"1080x1920","fps":3,"voice":"ru_RU-ruslan-medium→ru-RU-DmitryNeural","speech_rate":"length_scale=1.12 / +7%","text_overlay":False},ensure_ascii=False),flush=True)
        return out,tmp2
    except Exception as e:
        print("SELLER_VIDEO_BUILD_ERROR",type(e).__name__,str(e),flush=True)
        shutil.rmtree(tmp,ignore_errors=True)
        # Last-resort path: still use the resource-safe image renderer.
        # Do not call the legacy seller-video implementation.
        safe_tmp=tempfile.mkdtemp(prefix="cfvideo_safe_")
        out,_=_clean_image_video(content_id,row,offer,safe_tmp,ff)
        return out,safe_tmp

core._make_mp4=make_mp4_seller_first
print("CPA_VIDEO_ENGINE_VERSION",json.dumps({"version":"safe-image-v2","seller_transcode":"disabled","legacy_fallback":"disabled"},ensure_ascii=False),flush=True)
# Route every legacy/fallback video path through the production TTS chain too.
core._tts_audio=production_tts_audio

@core.app.get("/api/cpa/status")
def enhanced_status():
    with core.db() as c: active=int(c.execute("select count(*) n from offers where active=true").fetchone()["n"])
    return {
      "admitad_configured":bool(os.getenv("ADMITAD_ACCESS_TOKEN") and os.getenv("ADMITAD_WEBSITE_ID")),
      "gdeslon_configured":bool(os.getenv("GDESLON_API_TOKEN")),
      "yandex_market_configured":bool(os.getenv("YANDEX_MARKET_OAUTH") and (os.getenv("YANDEX_MARKET_PLACE_ID") or os.getenv("YANDEX_MARKET_CLID"))),
      "wordstat_configured":bool(os.getenv("YANDEX_SEARCH_API_KEY") and os.getenv("YANDEX_SEARCH_FOLDER_ID")),
      "active_offers":active
    }

_BOOT_LOCK = threading.Lock()
_BOOT_STARTED = False

def _deep_boot():
    global _BOOT_STARTED
    with _BOOT_LOCK:
        if _BOOT_STARTED:
            return
        _BOOT_STARTED = True
    try:
        import time
        print("CPA_DEEP_BOOT_STAGE",json.dumps({"stage":"start"},ensure_ascii=False),flush=True)

        ff=_ffmpeg_exe()
        if not ff:
            raise RuntimeError("ffmpeg недоступен")
        print("CPA_DEEP_BOOT_STAGE",json.dumps({"stage":"ffmpeg_ok","ffmpeg":ff},ensure_ascii=False),flush=True)

        # Wait briefly for the importer to populate offers. If content is
        # still absent, run one normal pipeline cycle ourselves so the
        # production preview is built from a real product, not a dummy file.
        import time
        for wait_no in range(1,7):
            with core.db() as c:
                offer_count=int(c.execute("select count(*) n from offers where active=true").fetchone()["n"])
                content_count=int(c.execute("select count(*) n from content").fetchone()["n"])
            print("CPA_DEEP_DATA_STATE",json.dumps({"offer_count":offer_count,"content_count":content_count,"wait":wait_no},ensure_ascii=False),flush=True)
            if content_count > 0:
                break
            if offer_count > 0:
                try:
                    result=core._pipeline_run()
                    print("CPA_DEEP_PIPELINE",json.dumps(result,ensure_ascii=False,default=str),flush=True)
                except Exception as e:
                    print("CPA_DEEP_PIPELINE_ERROR",type(e).__name__,str(e),flush=True)
                time.sleep(3)
                break
            time.sleep(5)

        test=None
        for attempt in range(1,9):
            print("CPA_DEEP_BOOT_STAGE",json.dumps({"stage":"video_build","attempt":attempt},ensure_ascii=False),flush=True)
            test=mp4_selftest()
            if test.get("status") == "ok":
                break
            if test.get("status") == "no_content":
                print("CPA_PREVIEW_WAIT",json.dumps({"attempt":attempt,"reason":"no_content"},ensure_ascii=False),flush=True)
                time.sleep(10)
                continue
            break

        if not test or test.get("status") != "ok":
            raise RuntimeError("MP4 self-test failed: "+str(test))

        preview=_LAST_PREVIEW_VIDEO.get("path")
        if not preview or not os.path.exists(preview):
            raise RuntimeError("Preview MP4 отсутствует после self-test")

        print("CPA_DEEP_BOOT_STAGE",json.dumps({"stage":"decode_check"},ensure_ascii=False),flush=True)
        p=subprocess.run([ff,"-v","error","-i",preview,"-f","null","-"],capture_output=True,text=True,timeout=180)
        if p.returncode!=0:
            raise RuntimeError("MP4 decode failed: "+p.stderr[-1000:])

        print("CPA_DEEP_PRODUCTION_TEST",json.dumps({
            "status":"ok",
            "content_id":test.get("content_id"),
            "bytes":test.get("bytes"),
            "ffmpeg":ff,
            "voice":"ru-RU-DmitryNeural",
            "mp4_decode":"ok",
            "preview":"/api/preview-video"
        },ensure_ascii=False),flush=True)
    except Exception as e:
        print("CPA_DEEP_PRODUCTION_TEST",json.dumps({
            "status":"error",
            "error":f"{type(e).__name__}: {e}"
        },ensure_ascii=False),flush=True)

@core.app.on_event("startup")
def enhancement_startup():
    # Startup is deliberately lightweight. Network imports, media crawling and
    # MP4 generation must never be part of the web process boot path.
    print("CPA_ENHANCEMENTS_STARTED",json.dumps({"gdeslon":bool(os.getenv("GDESLON_API_TOKEN")),"yandex_market":bool(os.getenv("YANDEX_MARKET_OAUTH")),"wordstat":bool(os.getenv("YANDEX_SEARCH_API_KEY") and os.getenv("YANDEX_SEARCH_FOLDER_ID"))}),flush=True)

