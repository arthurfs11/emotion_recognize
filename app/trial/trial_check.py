# app/config/trial_check.py
import socket
import psycopg2
from datetime import datetime
from typing import Optional

def _conn_trial(dbname, user, password, host, port):
    return psycopg2.connect(
        dbname=dbname, user=user, password=password, host=host, port=port
    )

def is_trial_active(license_key: str, db_cfg: dict, versao: str = "trial-1"):
    """
    Retorna (ativo: bool). Registra heartbeat.
    db_cfg = {DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT}
    """
    conn = None
    try:
        conn = _conn_trial(
            db_cfg["DB_NAME"], db_cfg["DB_USER"], db_cfg["DB_PASSWORD"],
            db_cfg["DB_HOST"], db_cfg["DB_PORT"]
        )
        cur = conn.cursor()
        cur.execute("SELECT ativo FROM licencas_trial WHERE license_key=%s", (license_key,))
        row = cur.fetchone()
        ativo = bool(row[0]) if row else False

        # heartbeat (mesmo se inativo, registra)
        try:
            cur.execute("""
                INSERT INTO trial_heartbeats(license_key, seen_at, host, versao)
                VALUES (%s, NOW(), %s, %s)
            """, (license_key, socket.gethostname(), versao))
            conn.commit()
        except Exception:
            conn.rollback()

        cur.close(); conn.close()
        return ativo
    except Exception:
        if conn:
            conn.close()
        return False
