import json, logging, os, time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("readsprint")
app=FastAPI(title="ReadSprint API", version="1.0.0")

origins=[
    "https://readsprint.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET","POST","OPTIONS"],
    allow_headers=["*"],
)

ALLOWED={"page_view","load_text","start_reading","pause_reading","finish_reading","file_open","speed_change","share","install_prompt","feedback_open","history_open"}

class Event(BaseModel):
    event: str = Field(min_length=1,max_length=50)
    session_id: str = Field(min_length=1,max_length=80)
    props: dict = Field(default_factory=dict)

class Feedback(BaseModel):
    session_id: str = Field(min_length=1,max_length=80)
    message: str = Field(min_length=3,max_length=1000)

@app.get("/")
def root():
    return {"ok":True,"service":"readsprint-api","version":"1.0.0"}

@app.get("/health")
def health():
    return {"ok":True,"ts":int(time.time())}

@app.post("/event")
async def event(e: Event, request: Request):
    if e.event not in ALLOWED:
        return {"ok":False,"ignored":True}
    safe_props={str(k)[:40]:str(v)[:120] for k,v in list(e.props.items())[:12]}
    log.info("READSPRINT_EVENT %s", json.dumps({
        "event":e.event,
        "session":e.session_id,
        "props":safe_props,
        "ua":(request.headers.get("user-agent") or "")[:180]
    }, ensure_ascii=False))
    return {"ok":True}

@app.post("/feedback")
async def feedback(f: Feedback):
    msg=" ".join(f.message.split())
    log.info("READSPRINT_FEEDBACK %s", json.dumps({
        "session":f.session_id,
        "message":msg
    }, ensure_ascii=False))
    return {"ok":True}
