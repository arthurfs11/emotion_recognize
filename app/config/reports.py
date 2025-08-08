import psycopg2, pandas as pd
from datetime import datetime, timedelta
import smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from decouple import config

DB_NAME = config("DB_NAME", default="emocional")
DB_USER = config("DB_USER", default="arthurfaria")
DB_PASSWORD = config("DB_PASSWORD", default="")
DB_HOST = config("DB_HOST", default="localhost")
DB_PORT = config("DB_PORT", default="5432")

SMTP_HOST = config("SMTP_HOST")
SMTP_PORT = config("SMTP_PORT", cast=int, default=587)
SMTP_USER = config("SMTP_USER")
SMTP_PASS = config("SMTP_PASS")
REPORT_TO  = config("REPORT_TO")
REPORT_FROM = config("REPORT_FROM", default=SMTP_USER)

def _q(sql, params=None):
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
                            host=DB_HOST, port=DB_PORT)
    df = pd.read_sql(sql, conn, params=params)
    conn.close()
    return df

def build_report(period_hours=24):
    t_end = datetime.now()
    t_start = t_end - timedelta(hours=period_hours)

    kpis = _q("""
        SELECT AVG(feliz) feliz, AVG(triste) triste, AVG(medo) medo, AVG(raiva) raiva,
               AVG(desgosto) desgosto, AVG(surpresa) surpresa, AVG(neutro) neutro, COUNT(*) leituras
        FROM leituras_emocionais
        WHERE data_captura BETWEEN %(ini)s AND %(fim)s
    """, {"ini": t_start, "fim": t_end}).iloc[0].fillna(0)

    dom = _q("""
        SELECT emocao_dominante, COUNT(*) qtd
        FROM leituras_emocionais
        WHERE data_captura BETWEEN %(ini)s AND %(fim)s
        GROUP BY emocao_dominante
        ORDER BY qtd DESC
        LIMIT 5
    """, {"ini": t_start, "fim": t_end})

    html = f"""
    <h2>Relatório Emocional — Últimas {period_hours}h</h2>
    <p><b>Janela:</b> {t_start:%d/%m %H:%M} → {t_end:%d/%m %H:%M}</p>
    <ul>
      <li>Leituras: <b>{int(kpis['leituras'])}</b></li>
      <li>Médias (%): feliz {kpis['feliz']:.1f} | triste {kpis['triste']:.1f} |
          medo {kpis['medo']:.1f} | raiva {kpis['raiva']:.1f} | neutro {kpis['neutro']:.1f}</li>
      <li><b>Preocupação (medo+triste): {(kpis['medo']+kpis['triste']):.1f}%</b></li>
    </ul>
    <h3>Top emoções dominantes</h3>
    {dom.to_html(index=False)}
    """
    return html

def send_email(html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Relatório Emocional"
    msg["From"] = REPORT_FROM
    msg["To"] = REPORT_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(context=ctx)
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def send_report(period_hours=24):
    send_email(build_report(period_hours))
