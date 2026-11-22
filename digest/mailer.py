"""Send the digest over SMTP. All settings come from environment variables."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr


def _env(name: str, default: str = "") -> str:
    # Secrets pasted into GitHub often carry a trailing newline or spaces
    return (os.environ.get(name) or default).strip()


def _sender(raw: str, user: str) -> str:
    """Build a well-formed From header from EMAIL_FROM.

    Accepts "name@x.com", "Name <name@x.com>", '"Name" <name@x.com>', or just a display
    name like "arXiv digest" (then SMTP_USER is used as the address).
    """
    raw = raw.strip().strip("'")
    if raw.startswith('"') and raw.endswith('"') and raw.count('"') == 2:
        raw = raw[1:-1]  # whole value wrapped in quotes
    name, addr = parseaddr(raw)
    if "@" not in addr:  # no usable address: treat the whole thing as a display name
        name, addr = raw.strip('"'), user
    return formataddr((name, addr)) if name else addr


def _mask(addr: str) -> str:
    local, _, domain = addr.partition("@")
    return f"{local[:2]}***@{domain}" if domain else f"{addr[:2]}***"


def _diagnose(host: str, port: int, user: str, password: str, s: smtplib.SMTP | None, err: Exception) -> None:
    """Print what can be checked without ever printing the password."""
    print("[mail] login failed:", type(err).__name__, err)
    print(f"[mail]   server        : {host}:{port} ({'SSL' if port == 465 else 'STARTTLS'})")
    print(f"[mail]   user          : {_mask(user)}  (looks like an email address: {'@' in user})")
    print(f"[mail]   password      : {len(password)} chars, ascii-only: {password.isascii()}, "
          f"contains spaces: {' ' in password}")
    if host == "smtp.gmail.com":
        print("[mail]   gmail expects : full address as user, a 16-letter app password "
              "(2-Step Verification must be on), not your normal password")
    if s is not None and getattr(s, "esmtp_features", None):
        print(f"[mail]   server offers : AUTH {s.esmtp_features.get('auth', '(none)')}")


def send(subject: str, html: str, text: str) -> None:
    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "587"))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    if host == "smtp.gmail.com":
        password = password.replace(" ", "")  # app passwords are shown as "abcd efgh ijkl mnop"
    to = [a.strip() for a in _env("EMAIL_TO").split(",") if a.strip()]
    sender = _sender(_env("EMAIL_FROM"), user)
    if not (user and password and to):
        raise SystemExit("[mail] SMTP_USER, SMTP_PASSWORD and EMAIL_TO must all be set")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    # EMAIL_FROM may be "Display Name <addr@domain>"; take the domain from the address part
    msg["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].split("@")[-1] or None)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    s: smtplib.SMTP | None = None
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
        else:
            s = smtplib.SMTP(host, port, timeout=60)
            s.ehlo()
            s.starttls(context=ctx)
        s.ehlo()
        s.login(user, password)
    except (smtplib.SMTPException, OSError) as e:
        _diagnose(host, port, user, password, s, e)
        raise
    try:
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except smtplib.SMTPException:
            pass
    print(f"[mail] sent to {len(to)} recipient(s) via {host}:{port}")
