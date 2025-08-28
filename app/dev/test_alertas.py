# app/dev/test_alertas.py
import os, time
from datetime import datetime, timezone

# --- sempre rode em modo dev para facilitar o disparo do alerta ---
os.environ.setdefault("WELLME_DEV", "1")

from app.services.alerts_storage import PostgresStorage
from app.services.alerts_engine import AlertManager
from app.config.database import salvar_em_banco, ensure_tables, _conn

USER_ID = "dev"   # separa do 'default' e evita cooldown/estado antigo
PESSOA  = "p1"

# --- prepara banco: tabelas + prefs do user_id 'dev' ---
def _prepare_db(reset_state: bool = True):
    ensure_tables()
    with _conn() as conn:
        cur = conn.cursor()
        # prefs para testes (sem quiet hours, cap alto)
        cur.execute("""
            INSERT INTO user_prefs (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING;
        """, (USER_ID,))
        cur.execute("""
            UPDATE user_prefs
               SET quiet_start='23:59', quiet_end='00:00', daily_cap=20, notify_enabled=TRUE
             WHERE user_id=%s;
        """, (USER_ID,))
        if reset_state:
            # limpa estado/cooldown para começar “zerado”
            cur.execute("DELETE FROM detector_state WHERE user_id=%s;", (USER_ID,))
            cur.execute("DELETE FROM stress_alerts WHERE user_id=%s;", (USER_ID,))
        conn.commit()

storage = PostgresStorage()
engine   = AlertManager(storage)

def sim(emocoes, recursos, pessoa=PESSOA, user_id=USER_ID, label=""):
    ts = datetime.now(timezone.utc)
    salvar_em_banco(emocoes, recursos, ts, pessoa, meta={"camera_status":"ok","face_status":"ok"})
    r = engine.process_sample(user_id, pessoa, ts, emocoes, recursos)
    flag = "🔔" if r.get("alert") else "·"
    print(f"{flag} {label} score={r['score']:.2f} z={r['z']:.2f} mu={r['mu']:.2f} sigma={r['sigma']:.2f} alert={r['alert']}")
    return r

def main():
    _prepare_db(reset_state=True)

    # base curta p/ não inflar variância
    base_emo = {"raiva":1,"medo":1,"triste":1,"desgosto":1,"feliz":40,"surpresa":1,"neutro":56}
    base_rec = {"cpu":5,"mem":10,"disk":5}
    for i in range(5):
        sim(base_emo, base_rec, label=f"base#{i+1}")
        time.sleep(0.2)

    # pico forte (deve bater no modo dev)
    pico_emo = {"raiva":60,"medo":50,"triste":40,"desgosto":30,"feliz":2,"surpresa":10,"neutro":5}
    pico_rec = {"cpu":95,"mem":90,"disk":70}
    sim(pico_emo, pico_rec, label="PICO#1")
    # um pequeno respiro ajuda a ver o banner
    time.sleep(1.0)

    # segundo pico (cooldown no dev é 5s; se quiser outro banner, espere um pouco)
    time.sleep(5.5)  # garante passar o cooldown dev
    sim(pico_emo, pico_rec, label="PICO#2")

    # volta normal
    for i in range(3):
        sim(base_emo, base_rec, label=f"base_return#{i+1}")
        time.sleep(0.2)

if __name__ == "__main__":
    main()
