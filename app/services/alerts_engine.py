# app/services/alerts_engine.py
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from app.services.alerts_storage import PostgresStorage, UserPrefs

import os, platform, subprocess, shutil
from pathlib import Path

# ====== Modo DEV/DEBUG ======
DEV   = os.getenv("WELLME_DEV", "0") == "1"
DEBUG = os.getenv("WELLME_DEBUG", "0") == "1"

def _dbg(msg: str):
    if DEBUG:
        print(f"[ALERTS-DEBUG] {msg}")

# ====== Hiperparâmetros ======
# Em DEV, baseline adapta mais rápido e thresholds baixos pra forçar alerta.
ALPHA = 0.20 if DEV else 0.06
BETA  = 0.20 if DEV else 0.06
Z_HIGH  = 1.20 if DEV else 2.25
Z_VHIGH = 2.00 if DEV else 3.00
COOLDOWN_HIGH  = timedelta(seconds=3) if DEV else timedelta(minutes=25)
COOLDOWN_VHIGH = timedelta(seconds=3) if DEV else timedelta(minutes=45)

# ====== Ícone do app (macOS) ======
# default: app/assets/wellme_icon.png (a partir deste arquivo em app/services/)
_DEFAULT_ICON = (Path(__file__).resolve().parents[1] / "assets" / "wellme_icon.png")
# WELLME_APP_ICON = Path(os.getenv("WELLME_APP_ICON", str(_DEFAULT_ICON))).expanduser().resolve()
WELLME_APP_ICON = Path('/Users/arthurfaria/Desktop/GitHub/emotion_recognize/logo.png').expanduser().resolve()


# === util ===
def _saopaulo_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()

def _parse_hhmm(s: str):
    """Aceita 'HH:MM' ou 'HH:MM:SS'."""
    if not s:
        return 0, 0
    s = str(s).strip()
    parts = s.split(":")
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    from datetime import datetime as _dt
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            dt = _dt.strptime(s, fmt)
            return dt.hour, dt.minute
        except Exception:
            pass
    return 0, 0

def in_quiet_hours(now_local: datetime, start_hhmm: str, end_hhmm: str) -> bool:
    s_h, s_m = _parse_hhmm(start_hhmm)
    e_h, e_m = _parse_hhmm(end_hhmm)
    start = now_local.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
    end   = now_local.replace(hour=e_h, minute=e_m, second=0, microsecond=0)
    return now_local >= start or now_local < end  # janela cruza meia-noite

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def compute_stress_score(emocoes: Dict[str, float], recursos: Dict[str, float]) -> float:
    """Robusto a escalas (0-1 ou 0-100). Retorna 0..100."""
    def val(d, k): return float(d.get(k, 0) or 0)
    emo_keys = ["raiva","medo","triste","desgosto","feliz","surpresa","neutro"]
    raw = [val(emocoes, k) for k in emo_keys]
    maxv = max(raw) if raw else 0
    if maxv > 1.0:  em = {k: (val(emocoes,k)/100.0) for k in emo_keys}
    else:           em = {k: clamp01(val(emocoes,k)) for k in emo_keys}

    neg = em["raiva"] + em["medo"] + em["triste"] + em["desgosto"]
    pos = em["feliz"]
    surpr = em["surpresa"]

    cpu = clamp01(val(recursos, "cpu")/100.0)
    mem = clamp01(val(recursos, "mem")/100.0)
    disk= clamp01(val(recursos, "disk")/100.0)
    load = 0.4*cpu + 0.4*mem + 0.2*disk

    score = 60.0*neg - 25.0*pos + 10.0*surpr + 45.0*load
    return float(max(0.0, min(100.0, score)))

# === EWMA detector ===
@dataclass
class EWMA:
    mu: float = 50.0
    var: float = 100.0
    initialized: bool = False

class PeakDetector:
    def __init__(self, state: Optional[Dict]=None):
        self.ew = EWMA()
        self.active_peak = False
        self.below_counter = 0
        if state:
            self.ew.mu = state["mu"]
            self.ew.var = state["var"]
            self.ew.initialized = state["initialized"]
            self.active_peak = state["active_peak"]
            self.below_counter = state["below_counter"]

    def _update_ew(self, x: float) -> Tuple[float,float]:
        if not self.ew.initialized:
            self.ew.mu = x
            self.ew.var = 50.0
            self.ew.initialized = True
            return self.ew.mu, max(self.ew.var, 1e-3)**0.5
        prev_mu = self.ew.mu
        self.ew.mu = (1-ALPHA)*self.ew.mu + ALPHA*x
        diff = x - prev_mu
        self.ew.var = (1-BETA)*self.ew.var + BETA*(diff*diff)
        sigma = max(self.ew.var, 1e-6)**0.5
        return self.ew.mu, sigma

    def step(self, x: float):
        mu, sigma = self._update_ew(x)
        z = 0.0 if sigma < 1e-6 else (x - mu)/sigma
        level = None
        if z >= Z_VHIGH:
            level = "very_high"; self.active_peak = True; self.below_counter = 0
        elif z >= Z_HIGH:
            level = "high"; self.active_peak = True; self.below_counter = 0
        else:
            if self.active_peak and z < 1.0:
                self.below_counter += 1
                if self.below_counter >= 3:
                    self.active_peak = False; self.below_counter = 0
        return z, mu, sigma, level

    def dump_state(self) -> Dict:
        return {
            "mu": self.ew.mu, "var": self.ew.var,
            "active_peak": self.active_peak,
            "below_counter": self.below_counter,
            "initialized": self.ew.initialized
        }

# === Notificações (macOS com ícone custom) ===
def _escape_applescript(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def _notify_mac_osascript(title: str, body: str) -> bool:
    """Fallback sem ícone custom."""
    if shutil.which("osascript") is None:
        _dbg("osascript não encontrado no PATH")
        return False
    cmd = ["osascript", "-e",
           f'display notification "{_escape_applescript(body)}" with title "{_escape_applescript(title)}"']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        _dbg(f"osascript falhou: rc={r.returncode} stderr={r.stderr.strip()}")
        return False
    return True

def _notify_mac(title: str, body: str, icon_path: Optional[Path] = None) -> bool:
    """
    Tenta, nesta ordem (com logs em DEBUG):
      1) pync (usa terminal-notifier por baixo) com appIcon/contentImage
      2) terminal-notifier direto
      3) osascript (sem imagem, último recurso)
    """
    icon = icon_path if (icon_path and isinstance(icon_path, Path) and icon_path.exists()) \
           else (WELLME_APP_ICON if isinstance(WELLME_APP_ICON, Path) and WELLME_APP_ICON.exists() else None)

    # 1) pync
    try:
        from pync import Notifier  # type: ignore
        kwargs = {"title": title}
        # appIcon funciona em algumas versões; contentImage mostra a imagem ao lado do texto (Big Sur+)
        if icon:
            kwargs["appIcon"] = str(icon)
            kwargs["contentImage"] = str(icon)
        _dbg(f"usando pync (icon={icon})")
        Notifier.notify(body, **kwargs)
        return True
    except Exception as e:
        _dbg(f"pync falhou: {e}")

    # 2) terminal-notifier direto
    tn = shutil.which("terminal-notifier")
    if tn:
        cmd = [tn, "-title", title, "-message", body]
        if icon:
            # -appIcon = ícone mostrado no Histórico; -contentImage = imagem no banner (Big Sur+)
            cmd += ["-appIcon", str(icon), "-contentImage", str(icon)]
        _dbg(f"usando terminal-notifier (icon={icon})")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return True
        _dbg(f"terminal-notifier falhou: {r.stderr.strip()}")

    # 3) fallback: osascript (sem ícone custom)
    _dbg("caindo para osascript (sem ícone custom)")
    return _notify_mac_osascript(title, body)


def _notify_linux(title: str, body: str) -> bool:
    try:
        subprocess.Popen(["notify-send", title, body])
        return True
    except Exception as e:
        _dbg(f"notify-send falhou: {e}")
        return False

# === Alert manager ===
class AlertManager:
    def __init__(self, storage: PostgresStorage):
        self.storage = storage

    def _can_send(self, user_id: str, level: str, now_local: datetime):
        prefs: UserPrefs = self.storage.get_user_prefs(user_id)
        if in_quiet_hours(now_local, prefs.quiet_start, prefs.quiet_end):
            _dbg(f"bloqueado: quiet_hours ({prefs.quiet_start}-{prefs.quiet_end})")
            return False, None
        if not prefs.notify_enabled:
            _dbg("bloqueado: notify_enabled=FALSE")
            return False, None

        start_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = self.storage.count_alerts(user_id, start_day)
        if sent_today >= (prefs.daily_cap or 4):
            _dbg(f"bloqueado: daily_cap atingido ({sent_today}/{prefs.daily_cap})")
            return False, None

        last = self.storage.get_last_alert(user_id)
        if last and last.get("cooldown_until"):
            now_utc = now_local.astimezone(timezone.utc)
            if now_utc < last["cooldown_until"]:
                _dbg(f"bloqueado: cooldown até {last['cooldown_until'].isoformat()}")
                return False, None

        cooldown = COOLDOWN_VHIGH if level == "very_high" else COOLDOWN_HIGH
        return True, cooldown

    def process_sample(self, user_id: str, pessoa_id: str, data_captura, emocoes: Dict, recursos: Dict):
        # 1) score
        score = compute_stress_score(emocoes, recursos)

        # 2) detector
        state = self.storage.get_detector_state(user_id)
        det = PeakDetector(state)
        z, mu, sigma, level = det.step(score)
        self.storage.save_detector_state(user_id, det.dump_state())

        # 3) grava métricas na leitura
        self.storage.update_sample_metrics(pessoa_id, data_captura, score, z, mu, sigma)

        # 4) decide alerta
        now_local = _saopaulo_now()
        if not level:
            _dbg(f"sem alerta: z={z:.2f} (HIGH>={Z_HIGH:.2f} | VHIGH>={Z_VHIGH:.2f})")
            return {"score": score, "z": z, "mu": mu, "sigma": sigma, "alert": None}

        ok, cooldown = self._can_send(user_id, level, now_local)
        if not ok:
            return {"score": score, "z": z, "mu": mu, "sigma": sigma, "alert": None}

        cooldown_until = now_local + cooldown
        alert_id = self.storage.create_alert(user_id, now_local, level, z, cooldown_until.astimezone(timezone.utc))

        title = "WellMe — pausa recomendada"
        body = "Pico de estresse! 5–7 min fora da tela e 1 copo d’água." if level == "very_high" else "Vamos respirar por 3–5 min?"

        ok_notify = False
        sys = platform.system()
        if sys == "Darwin":
            ok_notify = _notify_mac(title, body, WELLME_APP_ICON)
        elif sys == "Windows":
            # Se quiser suportar Windows, descomente e adicione win10toast no Windows:
            # try:
            #     from win10toast import ToastNotifier  # type: ignore
            #     ToastNotifier().show_toast(title, body, duration=8)
            #     ok_notify = True
            # except Exception as e:
            #     _dbg(f"toast Windows falhou: {e}")
            ok_notify = False
        else:
            ok_notify = _notify_linux(title, body)

        if ok_notify:
            self.storage.mark_alert_delivered(alert_id)
            _dbg(f"alerta entregue id={alert_id} level={level} z={z:.2f}")
        else:
            _dbg(f"notificação não entregue (id={alert_id})")

        return {"score": score, "z": z, "mu": mu, "sigma": sigma, "alert": {"id": alert_id, "level": level}}


# app/services/alerts_engine.py

def compute_stress_score(emocoes, recursos):
    """
    Retorna um score 0..100. Aceita emocoes=None.
    """
    # Normaliza quando vier None
    if emocoes is None:
        emocoes = {
            'raiva': 0.0, 'desgosto': 0.0, 'medo': 0.0,
            'feliz': 0.0, 'triste': 0.0, 'surpresa': 0.0, 'neutro': 1.0
        }

    emo_keys = ['medo', 'triste', 'raiva', 'feliz']  # use o que sua fórmula considera
    def val(d, k): 
        try:
            return float((d or {}).get(k, 0) or 0)
        except Exception:
            return 0.0

    raw = [val(emocoes, k) for k in emo_keys]

    # sua fórmula original (exemplo):
    base = 0.6*raw[0] + 0.4*raw[1] + 0.2*raw[2] - 0.2*raw[3]

    # opcional: leve influência de recursos se existirem
    if recursos:
        try:
            cpu = float(recursos.get('cpu', 0) or 0)
            base += max(0.0, (cpu - 70.0)) * 0.2 / 30.0  # empurra um pouco se CPU > 70
        except Exception:
            pass

    # clamp 0..100
    return max(0.0, min(100.0, base))
