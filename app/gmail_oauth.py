import os, base64, json
from email.message import EmailMessage
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

SCOPES=["https://www.googleapis.com/auth/gmail.send"]
REDIRECT_URI=os.getenv("GMAIL_REDIRECT_URI","https://dealfinder-mobile.onrender.com/api/gmail/callback")
_token_path=os.getenv("GMAIL_TOKEN_PATH","/data/gmail_token.json" if os.path.isdir("/data") else "gmail_token.json")

def _client_config():
    cid=os.getenv("GOOGLE_CLIENT_ID","").strip()
    secret=os.getenv("GOOGLE_CLIENT_SECRET","").strip()
    if not cid or not secret:
        raise RuntimeError("Не настроены GOOGLE_CLIENT_ID и GOOGLE_CLIENT_SECRET")
    return {"web":{"client_id":cid,"client_secret":secret,"auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","redirect_uris":[REDIRECT_URI]}}

def auth_url():
    flow=Flow.from_client_config(_client_config(),scopes=SCOPES,redirect_uri=REDIRECT_URI)
    url,state=flow.authorization_url(access_type="offline",include_granted_scopes="true",prompt="consent")
    return url,state

def finish(code):
    flow=Flow.from_client_config(_client_config(),scopes=SCOPES,redirect_uri=REDIRECT_URI)
    flow.fetch_token(code=code)
    creds=flow.credentials
    os.makedirs(os.path.dirname(_token_path) or ".",exist_ok=True)
    with open(_token_path,"w",encoding="utf-8") as f: f.write(creds.to_json())
    return {"status":"connected","email":gmail_profile(creds)}

def credentials():
    if not os.path.exists(_token_path): return None
    c=Credentials.from_authorized_user_file(_token_path,SCOPES)
    if c.expired and c.refresh_token:
        c.refresh(Request())
        with open(_token_path,"w",encoding="utf-8") as f: f.write(c.to_json())
    return c if c.valid else None

def gmail_profile(creds=None):
    creds=creds or credentials()
    if not creds: return None
    service=build("gmail","v1",credentials=creds)
    return service.users().getProfile(userId="me").execute().get("emailAddress")

def status():
    try:
        c=credentials()
        return {"connected":bool(c),"email":gmail_profile(c) if c else None,"redirect_uri":REDIRECT_URI}
    except Exception as e:
        return {"connected":False,"error":f"{type(e).__name__}: {e}","redirect_uri":REDIRECT_URI}

def send_email(to,subject,body):
    c=credentials()
    if not c: return {"status":"not_connected","auth_url":auth_url()[0]}
    msg=EmailMessage()
    msg["To"]=to; msg["Subject"]=subject
    msg.set_content(body)
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result=build("gmail","v1",credentials=c).users().messages().send(userId="me",body={"raw":raw}).execute()
    return {"status":"sent","to":to,"message_id":result.get("id")}
