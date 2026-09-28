#!/usr/bin/env python3
"""Envoie un mail quand l'URL du Quick Tunnel pollux change.

Lancé chaque minute par pollux-url-notify.timer. L'URL est lue sur l'endpoint
/quicktunnel du serveur de métriques de cloudflared, puis comparée à la
dernière envoyée (fichier d'état) : un mail par changement, pas par exécution.
"""

import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        sys.exit(f"variable d'environnement manquante : {name}")
    return value


METRICS_URL = env("NOTIFY_METRICS_URL", "http://127.0.0.1:20241/quicktunnel")
STATE_FILE = Path(env("NOTIFY_STATE_FILE", "/var/lib/pollux-url-notify/last-url"))
SMTP_HOST = env("NOTIFY_SMTP_HOST", "mail.mailo.com")
SMTP_PORT = int(env("NOTIFY_SMTP_PORT", "465"))
SMTP_USER = env("NOTIFY_SMTP_USER")
SMTP_PASSWORD = env("NOTIFY_SMTP_PASSWORD")
# Mailo refuse (554) un From qui n'est ni l'identifiant ni un alias déclaré.
MAIL_FROM = env("NOTIFY_MAIL_FROM", SMTP_USER)
MAIL_TO = env("NOTIFY_MAIL_TO", SMTP_USER)


def current_url():
    # Tunnel arrêté ou pas encore enregistré : rien à signaler, on réessaie
    # à la prochaine minute.
    try:
        with urllib.request.urlopen(METRICS_URL, timeout=5) as resp:
            hostname = json.load(resp).get("hostname")
    except (OSError, ValueError):
        return None
    return f"https://{hostname}" if hostname else None


def send(url):
    message = EmailMessage()
    message["Subject"] = f"pollux : nouvelle URL {url}"
    message["From"] = MAIL_FROM
    message["To"] = MAIL_TO
    message["Date"] = formatdate(localtime=True)
    message.set_content(
        f"Nouvelle URL du tunnel pollux :\n\n{url}\n\n"
        f"Côté client : POLLUX_SERVER={url}/t\n"
    )
    # 465 = SSL implicite, sinon STARTTLS.
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)


def main():
    url = current_url()
    if url is None:
        return
    last = STATE_FILE.read_text().strip() if STATE_FILE.exists() else ""
    if url == last:
        return
    # État écrit seulement après l'envoi : un échec SMTP sera retenté.
    send(url)
    STATE_FILE.write_text(url + "\n")
    print(f"URL envoyée : {url}")


if __name__ == "__main__":
    main()
