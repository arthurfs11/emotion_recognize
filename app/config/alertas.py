# app/services/alertas.py
import os
import json
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional, Iterable, Union, Dict, Any

try:
    import requests
except Exception:
    # se estiver empacotando em .exe, garanta que 'requests' esteja no requirements
    requests = None


# ============== helpers ==============

def _post_json(url: str, payload: dict, timeout: int = 8, retries: int = 1) -> bool:
    """POST JSON com retry leve e logs mínimos."""
    if requests is None:
        print("[ALERTAS] 'requests' não está disponível.")
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


def _ensure_list(x: Union[str, Iterable[str], None]) -> List[str]:
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    return [s for s in x if s]


def formatar_alerta_pausa(usuario: str,
                          estresse: float,
                          limiar: float,
                          janela: str = "últimos minutos",
                          detalhes: Optional[str] = None) -> str:
    """Mensagem padrão para 'pausa recomendada'."""
    base = (f"⚠️ *Pausa recomendada*"
            f"Usuário: {usuario}"
            f"Índice de estresse: {estresse:.1f} (limiar {limiar:.1f}) — {janela}.")
    if detalhes:
        base += f"{detalhes}"
        return base 


    # ============== Slack ==============

    def enviar_slack(texto: str,
                    webhook_url: Optional[str] = None,
                    *,
                    bot_token: Optional[str] = None,
                    channel: Optional[str] = None) -> bool:
        """
        Envia mensagem para Slack.
        Modos suportados:
        - Incoming Webhook (padrão): SLACK_WEBHOOK_URL
        - chat.postMessage via Bot: SLACK_BOT_TOKEN + SLACK_CHANNEL (ou args)
        """
        # 1) Webhook
        url = _coalesce_env("SLACK_WEBHOOK_URL", webhook_url)
        if url:
            payload = {"text": texto}
            return _post_json(url, payload)

        # 2) Fallback: Bot token
        tok = _coalesce_env("SLACK_BOT_TOKEN", bot_token)
        ch  = _coalesce_env("SLACK_CHANNEL", channel)
        if not (tok and ch):
            print("[ALERTAS] Slack não configurado (defina SLACK_WEBHOOK_URL ou SLACK_BOT_TOKEN/SLACK_CHANNEL).")
            return False
        if requests is None:
            print("[ALERTAS] 'requests' não está disponível.")
            return False
        try:
            api = "https://slack.com/api/chat.postMessage"
            headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"}
            payload = {"channel": ch, "text": texto}
            r = requests.post(api, headers=headers, json=payload, timeout=8)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
            ok = bool(data.get("ok"))
            if not ok:
                print(f"[ALERTAS] Slack bot falhou: {data}")
            return ok
        except Exception as e:
            print(f"[ALERTAS] Slack bot erro: {e}")
            return False


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
            "sections": [{"activityTitle": titulo, "text": texto.replace("", "<br>")}],
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
            print("[ALERTAS] 'requests' não está disponível.")
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
                    usar_tls: bool = True,
                    *,
                    cc: Optional[Iterable[str]] = None,
                    bcc: Optional[Iterable[str]] = None,
                    is_html: Optional[bool] = None,
                    attachments: Optional[List[Dict[str, Any]]] = None) -> bool:
        """
        Envia e-mail. Suporta texto ou HTML, CC/BCC e anexos.
        Env vars padrão:
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, SMTP_USE_TLS
        attachments: lista de dicts com {"filename", "content" (bytes|str), "maintype", "subtype"}
        """
        host = _coalesce_env("SMTP_HOST", smtp_host)
        port = int(_coalesce_env("SMTP_PORT", str(smtp_port) if smtp_port else "") or "587")
        user = _coalesce_env("SMTP_USER", smtp_user)
        pwd  = _coalesce_env("SMTP_PASS", smtp_pass)
        from_addr = _coalesce_env("EMAIL_FROM", remetente) or (user or "no-reply@example.com")
        usar_tls = usar_tls if usar_tls is not None else (os.getenv("SMTP_USE_TLS", "1").lower() in {"1","true","yes"})

        if not host or not user or not pwd:
            print("[ALERTAS] SMTP_HOST/SMTP_USER/SMTP_PASS não configurados.")
            return False

        to_list = _ensure_list(destinatarios)
        cc_list = _ensure_list(cc)
        bcc_list = _ensure_list(bcc)
        all_rcpts = to_list + cc_list + bcc_list
        if not all_rcpts:
            print("[ALERTAS] Nenhum destinatário informado.")
            return False

        # Infere HTML se não especificado
        if is_html is None:
            low = corpo.strip().lower()
            is_html = any(tag in low for tag in ("<html", "</p>", "<br", "<div", "</table>"))

        try:
            if is_html or attachments:
                msg = MIMEMultipart()
                msg.attach(MIMEText(corpo, 'html' if is_html else 'plain', _charset='utf-8'))
            else:
                msg = MIMEText(corpo, _charset='utf-8')
            msg["Subject"] = assunto
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_list)
            if cc_list:
                msg["Cc"] = ", ".join(cc_list)
            # BCC intencionalmente fora do cabeçalho

            # Anexos
            if attachments:
                for att in attachments:
                    fname = att.get("filename") or "anexo"
                    content = att.get("content", b"")
                    maintype = att.get("maintype", "application")
                    subtype = att.get("subtype", "octet-stream")
                    part = MIMEBase(maintype, subtype)
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    part.set_payload(content)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                    msg.attach(part)

            if usar_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=10) as server:
                    server.ehlo()
                    try:
                        server.starttls(context=context)
                        server.ehlo()
                    except smtplib.SMTPException:
                        pass
                    server.login(user, pwd)
                    server.sendmail(from_addr, all_rcpts, msg.as_string())
            else:
                with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                    server.login(user, pwd)
                    server.sendmail(from_addr, all_rcpts, msg.as_string())
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
            return enviar_slack(
                mensagem,
                webhook_url=kwargs.get("webhook_url"),
                bot_token=kwargs.get("bot_token"),
                channel=kwargs.get("channel"),
            )
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
            return enviar_email(
                assunto=titulo or "Alerta",
                corpo=mensagem,
                destinatarios=_ensure_list(to),
                smtp_host=kwargs.get("smtp_host"),
                smtp_port=kwargs.get("smtp_port"),
                smtp_user=kwargs.get("smtp_user"),
                smtp_pass=kwargs.get("smtp_pass"),
                remetente=kwargs.get("remetente"),
                usar_tls=kwargs.get("usar_tls", True),
                cc=kwargs.get("cc"),
                bcc=kwargs.get("bcc"),
                is_html=kwargs.get("is_html"),
                attachments=kwargs.get("attachments"),
            )
        print(f"[ALERTAS] Canal desconhecido: {canal}")
        return False
