import os,httpx
def notify(text):
 token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
 if not token or not chat:return {'status':'not_configured'}
 r=httpx.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':text},timeout=20); r.raise_for_status(); return {'status':'sent'}
