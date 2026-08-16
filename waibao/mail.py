"""通过 QQ 邮箱 IMAP 读取「灵感邮件」，转成念头。

用法：想到灵感时，用手机邮件 App 给自己发一封邮件（主题或正文一句话即可），
回到 agent 点「同步邮件」，它会读取这些未读的、发件人是自己的邮件并转成念头。

需要在 .env / Streamlit Secrets 配置：
  MAIL_USER = 你的 QQ 邮箱地址
  MAIL_PASS = QQ 邮箱的授权码（16 位，和 SMTP 共用一个授权码即可）
"""

from __future__ import annotations

import email
import imaplib
import os
from email.header import decode_header, make_header
from email.message import Message


def configured() -> bool:
    return bool(os.environ.get("MAIL_USER") and os.environ.get("MAIL_PASS"))


def _decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value or ""


def _get_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    return payload.decode("utf-8", "ignore").strip()
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        return (payload or b"").decode("utf-8", "ignore").strip()
    except Exception:
        return ""


def fetch_inspirations(limit: int = 20) -> list[str]:
    """读取收件箱里「自己发给自己」的未读邮件，返回文本，并标记已读。"""
    user = os.environ.get("MAIL_USER", "").strip()
    pwd = os.environ.get("MAIL_PASS", "").strip()
    if not user or not pwd:
        return []
    results: list[str] = []
    try:
        mbox = imaplib.IMAP4_SSL("imap.qq.com", 993)
        mbox.login(user, pwd)
        mbox.select("INBOX")
        typ, data = mbox.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            mbox.logout()
            return []
        ids = data[0].split()[-limit:]
        for mid in ids:
            try:
                typ2, msg_data = mbox.fetch(mid, "(RFC822)")
                if typ2 != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                frm = msg.get("From", "")
                if user.lower() not in frm.lower():
                    continue
                subj = _decode_header_value(msg.get("Subject", ""))
                body = _get_body(msg)
                text = (subj or body or "").strip()
                if text:
                    results.append(text)
                mbox.store(mid, "+FLAGS", "\\Seen")
            except Exception:
                continue
        mbox.logout()
    except Exception:
        pass
    return results
