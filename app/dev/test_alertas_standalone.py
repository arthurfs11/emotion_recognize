# app/dev/test_alertas_standalone.py
import os, time
from datetime import datetime, timezone
from typing import Dict, Optional

# Força modo dev (threshold baixo + cooldown curto)
os.environ.setdefault("WELLME_DEV", "1")
os.environ.setdefault("WELLME_DEBUG", "1")

from app.services.alerts_engine import AlertManager
from app.services.alerts_storage import UserPrefs  # usamos só o tipo

# ---------- Helper p/ construir UserPrefs (compatível com variações) ----------
def _build_user_prefs(**kwargs) -> UserPrefs:
    """
    Tenta construir UserPrefs de forma compatível com diferentes assinaturas.
    1) Primeiro tenta com todos os kwargs.
    2) Se falhar, usa apenas quiet_start, quiet_end, daily_cap, notify_enabled.
    """
    try:
        return UserPrefs(**kwargs)  # sua versão pode aceitar user_id
    except TypeError:
        minimal = {
            k: kwargs[k]
            for k in ("quiet_start", "quiet_end", "daily_cap", "notify_enabled")
            if k in kwargs
        }
        return UserPrefs(**minimal)

# ---------- Storage em memória (NÃO usa banco) ----------
class InMemoryStorage:
    def __init__(self):
        self._prefs = {}
        self._state = {}
        self._alerts = []
        self._next_id = 1

    def get_user_prefs(self, user_id: str) -> UserPrefs:
        if user_id not in self._prefs:
            self._prefs[user_id] = _build_user_prefs(
                user_id=user_id,            # será ignorado se sua classe não aceitar
                quiet_start="23:59",
                quiet_end="00:00",
                daily_cap=20,
                notify_enabled=True,
            )
        return self._prefs[user_id]

    def count_alerts(self, user_id: str, start_day) -> int:
        return sum(1 for a in self._alerts
                   if a["user_id"] == user_id and a["created_at"] >= start_day)

    def get_last_alert(self, user_id: str) -> Optional[Dict]:
        cand = [a for a in self._alerts if a["user_id"] == user_id]
        return max(cand, key=lambda x: x["created_at"]) if cand else None

    def create_alert(self, user_id: str, when_local, level: str, z: float, cooldown_until):
        alert = {
            "id": self._next_id,
            "user_id": user_id,
            "created_at": when_local,
            "level": level,
            "z": float(z),
            "cooldown_until": cooldown_until,
            "delivered": False,
        }
        self._alerts.append(alert)
        self._next_id += 1
        return alert["id"]

    def mark_alert_delivered(self, alert_id: int):
        for a in self._alerts:
            if a["id"] == alert_id:
                a["delivered"] = True
                return

    def get_detector_state(self, user_id: str) -> Optional[Dict]:
        return self._state.get(user_id)

    def save_detector_state(self, user_id: str, state: Dict):
        self._state[user_id] = dict(state)

    def update_sample_metrics(self, pessoa_id, data_captura, score, z, mu, sigma):
        # no-op: sem DB
        pass

# ---------- Simulador ----------
USER_ID = "standalone"
PESSOA  = "p1"

storage = InMemoryStorage()
engine  = AlertManager(storage)

def sim(emocoes: Dict[str, float], recursos: Dict[str, float], label=""):
    ts = datetime.now(timezone.utc)
    r = engine.process_sample(USER_ID, PESSOA, ts, emocoes, recursos)
    bell = "🔔" if r.get("alert") else "·"
    print(f"{bell} {label:<12} score={r['score']:.2f} z={r['z']:.2f} mu={r['mu']:.2f} sigma={r['sigma']:.2f} alert={r['alert']}")
    return r

def main():
    # baseline curta para não inflar a variância
    base_emo = {"raiva":1,"medo":1,"triste":1,"desgosto":1,"feliz":40,"surpresa":1,"neutro":56}
    base_rec = {"cpu":5,"mem":10,"disk":5}
    for i in range(5):
        sim(base_emo, base_rec, label=f"base#{i+1}")
        time.sleep(0.15)

    # pico forte (deve disparar em DEV)
    pico_emo = {"raiva":60,"medo":50,"triste":40,"desgosto":30,"feliz":2,"surpresa":10,"neutro":5}
    pico_rec = {"cpu":95,"mem":90,"disk":70}
    sim(pico_emo, pico_rec, label="PICO#1")

    # respeita cooldown curto (3s em DEV)
    time.sleep(3.5)
    sim(pico_emo, pico_rec, label="PICO#2")

    # volta normal
    for i in range(3):
        sim(base_emo, base_rec, label=f"return#{i+1}")
        time.sleep(0.15)

if __name__ == "__main__":
    main()
