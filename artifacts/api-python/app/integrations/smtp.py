from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


class SmtpError(Exception):
    pass


@dataclass
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_name: str
    from_email: str
    use_tls: bool = True


def _connect(config: SmtpConfig) -> smtplib.SMTP:
    if not config.host.strip():
        raise SmtpError("SMTP host is required")
    if not config.username.strip() or not config.password:
        raise SmtpError("SMTP username and password are required")
    if not config.from_email.strip():
        raise SmtpError("From email is required")

    if config.port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=30)
    else:
        server = smtplib.SMTP(config.host, config.port, timeout=30)
        if config.use_tls:
            server.starttls()
    server.login(config.username, config.password)
    return server


def test_smtp_connection(config: SmtpConfig) -> None:
    server = _connect(config)
    try:
        server.noop()
    finally:
        server.quit()


def send_email(
    config: SmtpConfig,
    *,
    to: list[str],
    subject: str,
    text: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    if not to:
        raise SmtpError("At least one recipient email is required")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config.from_name} <{config.from_email}>"
    message["To"] = ", ".join(to)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    for filename, content, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    server = _connect(config)
    try:
        server.send_message(message)
    finally:
        server.quit()


def send_test_email(config: SmtpConfig) -> None:
    send_email(
        config,
        to=[config.from_email],
        subject="Infosutra SMTP test",
        text="Your Brevo SMTP settings are working with Infosutra.",
        html="<p>Your Brevo SMTP settings are working with Infosutra.</p>",
    )
