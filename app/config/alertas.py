# app/services/alertas.py
import os
import json
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from typing import List, Optional
try:
    import requests
except Exception:
    # se estiver empacotando em .exe, garanta que 'requests' esteja no requirements
    requests = None


# ============== helpers ==============

def _post_json(url: str, payload: dict, timeout: int = 8, retries: int = 1) -> bool:
    """POST JSON com 1 retry leve."""
    if requests is None:
        return False
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if 200 <= r.status_code < 300:
                return True
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.4 * i)  # backoff simples
    print(f"[ALERTAS] POST falhou em {url}: {last_err}")
    return False


def _coalesce_env(name: str, val: Optional[str]) -> Optional[str]:
    """Prefere parâmetro; cai para variável de ambiente se None/''."""
    return val if val not in (None, "") else os.getenv(name)


def formatar_alerta_pausa(usuario: str,
                          estresse: float,
                          limiar: float,
                          janela: str = "últimos minutos",
                          detalhes: Optional[str] = None) -> str:
    """Mensagem padrão para 'pausa recomendada'."""
    base = (f"⚠️ *Pausa recomendada*\n"
            f"Usuário: {usuario}\n"
            f"Índice de estresse: {estresse:.1f} (limiar {limiar:.1f}) — {janela}.")
    if detalhes:
        base += f"\n{detalhes}"
    return base


# ============== Slack ==============

def enviar_slack(texto: str, webhook_url: Optional[str] = None) -> bool:
    """
    Envia mensagem para Slack via Incoming Webhook.
    Env var: SLACK_WEBHOOK_URL
    """
    url = _coalesce_env("SLACK_WEBHOOK_URL", webhook_url)
    if not url:
        print("[ALERTAS] SLACK_WEBHOOK_URL não configurada.")
        return False
    payload = {"text": texto}
    return _post_json(url, payload)


# ============== Microsoft Teams ==============

def enviar_teams(texto: str, webhook_url: Optional[str] = None, titulo: str = "Alerta") -> bool:
    """
    Envia para Teams via Incoming Webhook (conector).
    Env var: TEAMS_WEBHOOK_URL
    """
    url = _coalesce_env("TEAMS_WEBHOOK_URL", webhook_url)
    if not url:
        print("[ALERTAS] TEAMS_WEBHOOK_URL não configurada.")
        return False

    # Cartão MessageCard simples (compatível com Webhook do Teams)
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "EA4300",
        "summary": titulo,
        "sections": [{"activityTitle": titulo, "text": texto.replace("\n", "<br>")}],
    }
    return _post_json(url, payload)


# ============== Telegram ==============

def enviar_telegram(texto: str,
                    bot_token: Optional[str] = None,
                    chat_id: Optional[str] = None,
                    parse_mode: str = "Markdown") -> bool:
    """
    Envia mensagem pelo bot do Telegram.
    Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    """
    tok = _coalesce_env("TELEGRAM_BOT_TOKEN", bot_token)
    chat = _coalesce_env("TELEGRAM_CHAT_ID", chat_id)
    if not tok or not chat:
        print("[ALERTAS] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não configurados.")
        return False
    if requests is None:
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = {"chat_id": chat, "text": texto, "parse_mode": parse_mode, "disable_web_page_preview": True}
    return _post_json(url, payload)


# ============== E-mail (SMTP) ==============

def enviar_email(assunto: str,
                 corpo: str,
                 destinatarios: List[str],
                 smtp_host: Optional[str] = None,
                 smtp_port: Optional[int] = None,
                 smtp_user: Optional[str] = None,
                 smtp_pass: Optional[str] = None,
                 remetente: Optional[str] = None,
                 usar_tls: bool = True) -> bool:
    """
    Envia e-mail de texto.
    Env vars padrão:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM
    """
    host = _coalesce_env("SMTP_HOST", smtp_host)
    port = int(_coalesce_env("SMTP_PORT", str(smtp_port) if smtp_port else "") or "587")
    user = _coalesce_env("SMTP_USER", smtp_user)
    pwd  = _coalesce_env("SMTP_PASS", smtp_pass)
    from_addr = _coalesce_env("EMAIL_FROM", remetente) or (user or "no-reply@example.com")

    if not host or not user or not pwd:
        print("[ALERTAS] SMTP_HOST/SMTP_USER/SMTP_PASS não configurados.")
        return False

    try:
        msg = MIMEText(corpo, _charset="utf-8")
        msg["Subject"] = assunto
        msg["From"] = from_addr
        msg["To"] = ", ".join(destinatarios)

        if usar_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(user, pwd)
                server.sendmail(from_addr, destinatarios, msg.as_string())
        else:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, pwd)
                server.sendmail(from_addr, destinatarios, msg.as_string())
        return True
    except Exception as e:
        print(f"[ALERTAS] Falha ao enviar e-mail: {e}")
        return False


# ============== Dispatcher ==============

def enviar_alerta(canal: str,
                  mensagem: str,
                  titulo: Optional[str] = None,
                  **kwargs) -> bool:
    """
    Roteia para o canal desejado.
      canal ∈ {"slack","teams","telegram","email"}
    kwargs adicionais são repassados às funções específicas.
    """
    canal = (canal or "").strip().lower()
    if canal == "slack":
        return enviar_slack(mensagem, webhook_url=kwargs.get("webhook_url"))
    if canal == "teams":
        return enviar_teams(mensagem, webhook_url=kwargs.get("webhook_url"), titulo=titulo or "Alerta")
    if canal == "telegram":
        return enviar_telegram(
            mensagem,
            bot_token=kwargs.get("bot_token"),
            chat_id=kwargs.get("chat_id"),
            parse_mode=kwargs.get("parse_mode", "Markdown"),
        )
    if canal == "email":
        to = kwargs.get("destinatarios") or kwargs.get("para") or []
        if isinstance(to, str):
            to = [to]
        return enviar_email(
            assunto=titulo or "Alerta",
            corpo=mensagem,
            destinatarios=to,
            smtp_host=kwargs.get("smtp_host"),
            smtp_port=kwargs.get("smtp_port"),
            smtp_user=kwargs.get("smtp_user"),
            smtp_pass=kwargs.get("smtp_pass"),
            remetente=kwargs.get("remetente"),
            usar_tls=kwargs.get("usar_tls", True),
        )
    print(f"[ALERTAS] Canal desconhecido: {canal}")
    return False
