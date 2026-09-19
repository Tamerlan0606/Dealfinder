import os,smtplib
from email.message import EmailMessage
def send(to,subject,body):
 if os.getenv('DRY_RUN','true').lower()=='true': return {'status':'dry_run','to':to}
 m=EmailMessage(); m['From']=os.environ['SMTP_FROM']; m['To']=to; m['Subject']=subject; m.set_content(body)
 with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587'))) as s:
  s.starttls(); s.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']); s.send_message(m)
 return {'status':'sent','to':to}
