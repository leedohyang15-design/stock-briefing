"""SMTP 이메일 발송.

Gmail 기준: smtp.gmail.com:587, STARTTLS, 앱 비밀번호 사용.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .config import config


def send_email(subject: str, text_body: str, html_body: str) -> None:
    """설정된 수신자 전원에게 브리핑 이메일을 발송."""
    config.validate_for_send()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((config.mail_from_name, config.smtp_user))
    msg["To"] = ", ".join(config.mail_to)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config.smtp_user, config.smtp_password)
        server.sendmail(config.smtp_user, config.mail_to, msg.as_string())

    print(f"[sender] 발송 완료 → {', '.join(config.mail_to)}")
