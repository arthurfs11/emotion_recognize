# app/config/trial_csv.py
import os, csv, platform
from datetime import datetime
from typing import Dict, Optional

def _desktop_path() -> str:
    home = os.path.expanduser("~")
    system = platform.system().lower()
    # macOS/Linux
    desk = os.path.join(home, "Desktop")
    if os.path.isdir(desk):
        return desk
    # Windows fallback
    return os.path.join(home, "Desktop")

def csv_path_for_trial(license_key: str) -> str:
    dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    desk = _desktop_path()
    fname = f"wellio_trial_{license_key}_{dt}.csv"
    return os.path.join(desk, fname)

_HEADERS = [
    "data_hora",
    "emocao_dominante",
    "feliz","triste","medo","raiva","desgosto","surpresa","neutro",
    "brilho","qualidade","face_status","camera_status","mesma_pessoa","face_distance",
    "cpu","memoria","disco"
]

def ensure_csv_with_header(csv_path: str):
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(_HEADERS)

def append_trial_row(csv_path: str,
                     data_hora: datetime,
                     emocoes: Optional[Dict[str, float]],
                     dominante: str,
                     meta: Dict,
                     recursos: Dict[str, float]):
    row = [
        data_hora.isoformat(timespec="seconds"),
        dominante,
        (emocoes or {}).get("feliz",0),
        (emocoes or {}).get("triste",0),
        (emocoes or {}).get("medo",0),
        (emocoes or {}).get("raiva",0),
        (emocoes or {}).get("desgosto",0),
        (emocoes or {}).get("surpresa",0),
        (emocoes or {}).get("neutro",0),
        meta.get("brilho"),
        meta.get("qualidade"),
        meta.get("face_status"),
        meta.get("camera_status"),
        meta.get("mesma_pessoa"),
        meta.get("face_distance"),
        recursos.get("cpu",0),
        recursos.get("mem",0),
        recursos.get("disk",0),
    ]
    with open(csv_path, "a", newline="") as f:
        csv.writer(f).writerow(row)
