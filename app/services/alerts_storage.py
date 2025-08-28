# app/services/alerts_storage.py
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any
from app.config.database import _conn

@dataclass
class UserPrefs:
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    daily_cap: int = 4
    notify_enabled: bool = True

class PostgresStorage:
    # ----- prefs -----
    def get_user_prefs(self, user_id: str) -> UserPrefs:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT quiet_start::text, quiet_end::text, daily_cap, notify_enabled
                  FROM user_prefs WHERE user_id=%s
            """, (user_id,))
            r = cur.fetchone()
        if not r:
            return UserPrefs()
        return UserPrefs(r[0], r[1], r[2], r[3])

    def count_alerts(self, user_id: str, since: datetime) -> int:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
               SELECT COUNT(*) FROM stress_alerts
                WHERE user_id=%s AND ts >= %s
            """, (user_id, since))
            (n,) = cur.fetchone()
            return n

    def get_last_alert(self, user_id: str) -> Optional[Dict[str, Any]]:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
               SELECT alert_id, user_id, ts, level, z, cooldown_until, delivered, response, closed_ts
                 FROM stress_alerts
                WHERE user_id=%s
             ORDER BY ts DESC LIMIT 1
            """, (user_id,))
            r = cur.fetchone()
        if not r:
            return None
        keys = ["alert_id","user_id","ts","level","z","cooldown_until","delivered","response","closed_ts"]
        return dict(zip(keys, r))

    # ----- detector state -----
    def get_detector_state(self, user_id: str):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
              SELECT mu, var, active_peak, below_counter, initialized
                FROM detector_state WHERE user_id=%s
            """, (user_id,))
            r = cur.fetchone()
        if not r:
            return None
        return {
            "mu": r[0], "var": r[1],
            "active_peak": bool(r[2]),
            "below_counter": r[3],
            "initialized": bool(r[4])
        }

    def save_detector_state(self, user_id: str, state: Dict[str, Any]):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
              INSERT INTO detector_state (user_id, mu, var, active_peak, below_counter, initialized, updated_at)
              VALUES (%s,%s,%s,%s,%s,%s, NOW())
              ON CONFLICT (user_id) DO UPDATE SET
                 mu=EXCLUDED.mu, var=EXCLUDED.var, active_peak=EXCLUDED.active_peak,
                 below_counter=EXCLUDED.below_counter, initialized=EXCLUDED.initialized,
                 updated_at=NOW()
            """, (
                user_id, state["mu"], state["var"],
                state["active_peak"], state["below_counter"], state["initialized"]
            ))
            conn.commit()

    # ----- samples (atualização das colunas novas) -----
    def update_sample_metrics(self, pessoa_id: str, data_captura, stress_score: float, z: float, mu: float, sigma: float):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
              UPDATE leituras_emocionais
                 SET stress_score=%s, z=%s, mu=%s, sigma=%s
               WHERE pessoa_id=%s AND data_captura=%s
            """, (stress_score, z, mu, sigma, pessoa_id, data_captura))
            conn.commit()

    # ----- alerts -----
    def create_alert(self, user_id: str, ts: datetime, level: str, z: float, cooldown_until: datetime) -> int:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
              INSERT INTO stress_alerts (user_id, ts, level, z, cooldown_until)
              VALUES (%s,%s,%s,%s,%s) RETURNING alert_id
            """, (user_id, ts, level, z, cooldown_until))
            (alert_id,) = cur.fetchone()
            conn.commit()
            return alert_id

    def mark_alert_delivered(self, alert_id: int):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE stress_alerts SET delivered=TRUE WHERE alert_id=%s", (alert_id,))
            conn.commit()

    def record_alert_response(self, alert_id: int, action: str, closed_ts: Optional[datetime]=None):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
               UPDATE stress_alerts SET response=%s, closed_ts=COALESCE(%s, NOW())
                WHERE alert_id=%s
            """, (action, closed_ts, alert_id))
            conn.commit()
