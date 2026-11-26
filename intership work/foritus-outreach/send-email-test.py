import smtplib
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # 465 for SSL, or 587 for STARTTLS
SMTP_USER = "mannpatel1630@gmail.com"
SMTP_PASS = "gkfwmtumageohytc".replace(" ", "")
TO_EMAIL = "kushalbamania7@gmail.com"

msg = EmailMessage()
msg["Subject"] = "SMTP Debug Test"
msg["From"] = SMTP_USER
msg["To"] = TO_EMAIL
msg.set_content("Simple SMTP debug test.")

try:
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.set_debuglevel(1)
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.set_debuglevel(1)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    print("\nDEBUG RESULT: SUCCESS")
except Exception as exc:
    print(f"\nDEBUG RESULT: FAILED -> {type(exc).__name__}: {exc}")