import os, re, json, html, urllib.request, urllib.parse, tempfile, subprocess, shutil, threading, hashlib
from fastapi import Header, HTTPException
from fastapi.responses import Response

import app as core

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

def enrich_existing():
    try:
        with core.db() as c:
            rows=c.execute("select id,site_url,image_url,image_url2,video_url,video_url2 from offers where active=true and (video_url is null or video_url='') order by id desc limit 20").fetchall()
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

def wordstat_count(phrase):
    token=os.getenv("YANDEX_WORDSTAT_OAUTH","").strip()
    if not token or not phrase: return 0
    try:
        regions=[int(x) for x in os.getenv("YANDEX_WORDSTAT_REGIONS","").split(",") if x.strip().isdigit()]
        devices=[x.strip() for x in os.getenv("YANDEX_WORDSTAT_DEVICES","phone").split(",") if x.strip()]
        body={"phrase":str(phrase)[:300]}
        if regions: body["regions"]=regions
        if devices: body["devices"]=devices
        req=urllib.request.Request("https://api.wordstat.yandex.net/v1/topRequests",
          data=json.dumps(body,ensure_ascii=False).encode(),headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=20) as r: data=json.loads(r.read().decode())
        rows=data.get("topRequests") or []
        exact=[int(x.get("count") or 0) for x in rows if str(x.get("phrase","")).strip().lower()==str(phrase).strip().lower()]
        return max(exact or [max([int(x.get("count") or 0) for x in rows] or [0])])
    except Exception as e:
        print("WORDSTAT_ERROR",type(e).__name__,str(e),flush=True)
        return 0

def refresh_demand(limit=30):
    if not os.getenv("YANDEX_WORDSTAT_OAUTH","").strip():
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
        refresh_demand(30)
        enrich_existing()
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

def mp4_selftest():
    try:
        with core.db() as c:
            row=c.execute("select * from content order by id desc limit 1").fetchone()
            if not row: return {"status":"no_content"}
            offer_id=row["offer_id"] if "offer_id" in row.keys() else None
            offer=c.execute("select * from offers where id=%s",(offer_id,)).fetchone() if offer_id else c.execute("select * from offers order by id desc limit 1").fetchone()
        row=dict(row); offer=dict(offer) if offer else {}\n        path,tmp=core._make_mp4(row["id"],row,offer)
        size=os.path.getsize(path)
        shutil.rmtree(tmp,ignore_errors=True)
        result={"status":"ok","content_id":row["id"],"bytes":size,"seller_video":bool(offer.get("video_url") or offer.get("video_url2")) if hasattr(offer,"get") else False}
        print("MP4_PRODUCTION_SELFTEST",json.dumps(result,ensure_ascii=False),flush=True)
        return result
    except Exception as e:
        result={"status":"error","error":f"{type(e).__name__}: {e}"}
        print("MP4_PRODUCTION_SELFTEST",json.dumps(result,ensure_ascii=False),flush=True)
        return result

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
def make_mp4_seller_first(content_id,row,offer):
    # If seller video exists, use it as the visual source. Otherwise keep the proven generator.
    if not (offer.get("video_url") or offer.get("video_url2") or offer.get("site_url")):
        return _original_make(content_id,row,offer)
    tmp=tempfile.mkdtemp(prefix="cfvideo_")
    try:
        ff=shutil.which("ffmpeg")
        if not ff:
            try:
                import imageio_ffmpeg; ff=imageio_ffmpeg.get_ffmpeg_exe()
            except Exception: ff=None
        if not ff: return _original_make(content_id,row,offer)
        pack=core.build_content_pack(row,offer); scenes=pack["scenes"]
        video=seller_video(offer,tmp)
        if not video: return _original_make(content_id,row,offer)
        probe=subprocess.run([ff,"-i",video],capture_output=True,text=True,timeout=20)
        m=re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)",probe.stderr)
        vd=float(m.group(1))*3600+float(m.group(2))*60+float(m.group(3)) if m else 10
        parts=[]; durations=[]
        for i,sc in enumerate(scenes,1):
            text=core._video_text(sc.get("text","")); audio=os.path.join(tmp,f"a{i}.mp3")
            try:
                core._tts_audio(text,audio)
                pr=subprocess.run([ff,"-i",audio],capture_output=True,text=True,timeout=15)
                am=re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)",pr.stderr)
                ad=float(am.group(1))*3600+float(am.group(2))*60+float(am.group(3)) if am else 4.2
            except Exception:
                audio=None; ad=4.2
            dur=max(3.8,min(6.0,ad+0.35)); durations.append(dur)
            seg=os.path.join(tmp,f"s{i}.mp4")
            off=0 if vd<=1 else ((i-1)*4.5)%max(vd-1,1)
            cmd=[ff,"-y","-stream_loop","-1","-ss",f"{off:.2f}","-i",video]
            if audio:
                cmd += ["-i",audio,"-t",f"{dur:.2f}","-vf","scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,format=yuv420p","-r","24","-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k","-shortest",seg]
            else:
                cmd += ["-t",f"{dur:.2f}","-vf","scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,format=yuv420p","-r","24","-c:v","libx264","-preset","veryfast","-crf","23","-an",seg]
            subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
            parts.append(seg)
        concat=os.path.join(tmp,"concat.txt")
        with open(concat,"w",encoding="utf-8") as f:
            for p in parts: f.write(f"file '{p}'\n")
        out=os.path.join(tmp,f"content_{content_id}.mp4")
        subprocess.run([ff,"-y","-f","concat","-safe","0","-i",concat,"-c","copy","-movflags","+faststart",out],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)
        print("VIDEO_BUILD",json.dumps({"content_id":content_id,"seller_video":True,"duration":round(sum(durations),1),"voice":True},ensure_ascii=False),flush=True)
        return out,tmp
    except Exception as e:
        print("SELLER_VIDEO_BUILD_ERROR",type(e).__name__,str(e),flush=True)
        shutil.rmtree(tmp,ignore_errors=True)
        return _original_make(content_id,row,offer)

core._make_mp4=make_mp4_seller_first

@core.app.get("/api/cpa/status")
def enhanced_status():
    with core.db() as c: active=int(c.execute("select count(*) n from offers where active=true").fetchone()["n"])
    return {
      "admitad_configured":bool(os.getenv("ADMITAD_ACCESS_TOKEN") and os.getenv("ADMITAD_WEBSITE_ID")),
      "gdeslon_configured":bool(os.getenv("GDESLON_API_TOKEN")),
      "yandex_market_configured":bool(os.getenv("YANDEX_MARKET_OAUTH") and (os.getenv("YANDEX_MARKET_PLACE_ID") or os.getenv("YANDEX_MARKET_CLID"))),
      "wordstat_configured":bool(os.getenv("YANDEX_WORDSTAT_OAUTH")),
      "active_offers":active
    }

@core.app.on_event("startup")
def enhancement_startup():
    migrate()
    def _source_boot():
        import time
        try:
            time.sleep(20)
            enrich_existing()
            result=pipeline_with_demand()
            print("CPA_BOOT_PIPELINE",json.dumps(result,ensure_ascii=False,default=str),flush=True)
            mp4_selftest()
        except Exception as e:
            print("CPA_BOOT_PIPELINE_ERROR",type(e).__name__,str(e),flush=True)
    threading.Thread(target=_source_boot,daemon=True).start()
    print("CPA_ENHANCEMENTS_STARTED",json.dumps({
      "gdeslon":bool(os.getenv("GDESLON_API_TOKEN")),
      "yandex_market":bool(os.getenv("YANDEX_MARKET_OAUTH")),
      "wordstat":bool(os.getenv("YANDEX_WORDSTAT_OAUTH"))
    }),flush=True)
