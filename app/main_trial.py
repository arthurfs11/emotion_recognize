# app/main_trial.py
import os, sys, time, csv
from datetime import datetime, timedelta, timezone
import re
import psutil
import psycopg2
from psycopg2.extras import RealDictCursor

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

NEON_DB_URL = "postgresql://neondb_owner:npg_7Mkvmpwc2tuT@ep-broad-boat-ack6fc3f-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

# ===== NOVOS IMPORTS P/ EMOÇÕES REAIS =====
import cv2
try:
    # Se existir no seu projeto, usaremos preferencialmente
    from config.emocao import analisar_emocao as _analisar_emocao
except Exception:
    _analisar_emocao = None

try:
    import tkinter as tk
    from tkinter import simpledialog, messagebox
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False


# ========== COLETA DE EMOÇÕES (REAL) ==========
def init_camera():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        raise RuntimeError("Não foi possível abrir a webcam (VideoCapture(0)).")
    return cap

def _mapear_emocoes_en_pt(emotions_en: dict) -> dict:
    mapa = {
        "happy": "feliz",
        "sad": "triste",
        "fear": "medo",
        "angry": "raiva",
        "disgust": "desgosto",
        "surprise": "surpresa",
        "neutral": "neutro",
    }
    filtrado = { mapa[k]: float(v) for k, v in emotions_en.items() if k in mapa }
    total = sum(filtrado.values()) or 0.0
    if total > 0:
        return {k: round(v * 100.0 / total, 2) for k, v in filtrado.items()}
    return {"feliz":0,"triste":0,"medo":0,"raiva":0,"desgosto":0,"surpresa":0,"neutro":100.0}

def _normalizar_pt(p: dict) -> dict:
    padrao = {"feliz":0.0,"triste":0.0,"medo":0.0,"raiva":0.0,"desgosto":0.0,"surpresa":0.0,"neutro":0.0}
    for k in list(p.keys()):
        if k not in padrao:
            p.pop(k, None)
    padrao.update({k: float(v) for k, v in p.items() if k in padrao})
    s = sum(padrao.values()) or 0.0
    if s > 0:
        return {k: round(v * 100.0 / s, 2) for k, v in padrao.items()}
    padrao["neutro"] = 100.0
    return padrao

def coletar_emocoes_reais(cap) -> dict:
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError("Falha ao ler frame da webcam.")

    # 1) Preferência: sua função do projeto
    if _analisar_emocao is not None:
        try:
            res = _analisar_emocao(frame) or {}
            # Caso venha em EN (DeepFace-like)
            if any(k in res for k in ("happy","sad","fear","angry","disgust","surprise","neutral")):
                return _mapear_emocoes_en_pt(res)
            # Caso já venha em PT
            return _normalizar_pt(res)
        except Exception:
            pass  # Plano B

    # 2) Plano B: DeepFace direto
    try:
        from deepface import DeepFace
        analysis = DeepFace.analyze(
            img_path=frame,
            actions=["emotion"],
            enforce_detection=False
        )
        if isinstance(analysis, list):
            analysis = analysis[0]
        emotions = analysis.get("emotion") or analysis
        return _mapear_emocoes_en_pt(emotions)
    except Exception as e:
        print(f"[WARN] DeepFace/análise falhou: {e}")
        return {"feliz":0,"triste":0,"medo":0,"raiva":0,"desgosto":0,"surpresa":0,"neutro":100.0}


# ========== RECURSOS DO SISTEMA ==========
def coletar_recursos():
    return {"cpu": psutil.cpu_percent(interval=1),
            "mem": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent}


# --- util p/ comparar datetimes com/sem timezone ---
def _now_like(dt: datetime) -> datetime:
    if isinstance(dt, datetime) and dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None:
        return datetime.now(dt.tzinfo)
    return datetime.now()

def _fmt_dt(dt: datetime) -> str:
    try:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if dt.tzinfo else dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)

def _tk_askstring(title, prompt):
    if not TK_AVAILABLE: raise RuntimeError("Tk indisponível")
    root = tk.Tk(); root.withdraw(); root.update()
    try:
        val = simpledialog.askstring(title, prompt, parent=root); root.update(); return val
    finally:
        try: root.destroy()
        except Exception: pass

def _tk_info(title, msg):
    if not TK_AVAILABLE: raise RuntimeError("Tk indisponível")
    root = tk.Tk(); root.withdraw(); root.update()
    try:
        messagebox.showinfo(title, msg, parent=root); root.update()
    finally:
        try: root.destroy()
        except Exception: pass

def _tk_error(title, msg):
    if not TK_AVAILABLE: raise RuntimeError("Tk indisponível")
    root = tk.Tk(); root.withdraw(); root.update()
    try:
        messagebox.showerror(title, msg, parent=root); root.update()
    finally:
        try: root.destroy()
        except Exception: pass

def pedir_email():
    try:
        v = _tk_askstring("Trial - Login", "Digite seu e-mail para iniciar:")
        return (v or "").strip() if v else None
    except Exception:
        try: return input("Digite seu e-mail para iniciar: ").strip()
        except Exception: return None

def alert(titulo, msg):
    try: _tk_info(titulo, msg)
    except Exception: print(f"[{titulo}] {msg}")

def alert_erro(titulo, msg):
    try: _tk_error(titulo, msg)
    except Exception: print(f"[{titulo}] {msg}")

def email_valido(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(email or "").strip()))

# ---------- DB ----------
def trial_conn():
    if not NEON_DB_URL or "postgres" not in NEON_DB_URL:
        raise RuntimeError("NEON_DB_URL não configurada.")
    ssl_kwargs = {}
    try:
        import certifi
        ssl_kwargs["sslrootcert"] = certifi.where()
    except Exception:
        pass
    return psycopg2.connect(NEON_DB_URL, connect_timeout=10, **ssl_kwargs)

def checar_trial_por_email(email: str):
    try:
        conn = trial_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT email, ativo, expires_at
                  FROM trial_licencas
                 WHERE email = %s
                 LIMIT 1
            """, (email,))
            row = cur.fetchone()
        conn.close()
        return row
    except Exception as e:
        alert_erro("Não foi possível consultar o servidor de licença", str(e))
        sys.exit(1)

# ---------- CSV/PDF ----------
def caminho_csv_na_area_de_trabalho(email: str) -> str:
    desktop = _get_desktop_dir()
    fname = f"trial_emocoes_{email.replace('@','_').replace('.','_')}.csv"
    return os.path.join(desktop, fname)

def caminho_pdf_na_area_de_trabalho(email: str) -> str:
    desktop = _get_desktop_dir()
    fname = f"trial_relatorio_{email.replace('@','_').replace('.','_')}.pdf"
    return os.path.join(desktop, fname)

def preparar_csv(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "data_hora","feliz","triste","medo","raiva","desgosto","surpresa","neutro",
                "cpu","memoria","disco"
            ])

def append_csv(path: str, data_hora, emocoes, rec):
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            data_hora.strftime("%Y-%m-%d %H:%M:%S"),
            emocoes.get("feliz",0), emocoes.get("triste",0), emocoes.get("medo",0),
            emocoes.get("raiva",0), emocoes.get("desgosto",0), emocoes.get("surpresa",0), emocoes.get("neutro",0),
            rec.get("cpu",0), rec.get("mem",0), rec.get("disk",0)
        ])

# --- Desktop cross-platform (Windows OneDrive / macOS iCloud / Linux XDG) ---
def _get_desktop_dir() -> str:
    import os, sys, re
    home = os.path.expanduser("~")
    candidates = []

    if sys.platform.startswith("win"):
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            root = os.environ.get(key)
            if root:
                candidates.append(os.path.join(root, "Desktop"))
        userprofile = os.environ.get("USERPROFILE", home)
        if os.path.isdir(userprofile):
            try:
                for name in os.listdir(userprofile):
                    if name.lower().startswith("onedrive"):
                        candidates.append(os.path.join(userprofile, name, "Desktop"))
            except Exception:
                pass
        candidates.append(os.path.join(userprofile, "Desktop"))

    elif sys.platform == "darwin":
        candidates.append(os.path.join(home, "Library", "Mobile Documents", "com~apple~CloudDocs", "Desktop"))
        candidates.append(os.path.join(home, "Desktop"))

    else:
        userdirs = os.path.join(home, ".config", "user-dirs.dirs")
        if os.path.isfile(userdirs):
            try:
                with open(userdirs, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                m = re.search(r'XDG_DESKTOP_DIR="?(.+?)"?\n', txt)
                if m:
                    path = m.group(1).replace("$HOME", home)
                    candidates.append(os.path.expandvars(path))
            except Exception:
                pass
        candidates.append(os.path.join(home, "Desktop"))

    for p in candidates:
        if p and os.path.isdir(p):
            return p

    fallback = candidates[-1] if candidates else os.path.join(home, "Desktop")
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        pass
    return fallback


def gerar_pdf_relatorio(csv_path: str, out_path: str = None, titulo: str = None):
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as e:
        alert("Relatório", f"Dependências ausentes para PDF (pandas/matplotlib). Pulando.\n{e}")
        return None

    try:
        df = pd.read_csv(csv_path)
        df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce")
        df = df.sort_values("data_hora").reset_index(drop=True)
        if df.empty:
            alert("Relatório", "CSV sem dados — não foi gerado PDF.")
            return None

        EMOCOES = ["feliz","triste","medo","raiva","desgosto","surpresa","neutro"]
        titulo = titulo or "Relatório Trial"
        out_path = out_path or os.path.splitext(csv_path)[0] + "_relatorio.pdf"

        info = {"leituras": len(df), "inicio": df["data_hora"].min(), "fim": df["data_hora"].max()}
        for c in EMOCOES + ["cpu","memoria","disco"]:
            if c in df.columns:
                info[f"media_{c}"] = float(df[c].mean())
        dom = {e: info.get(f"media_{e}", 0.0) for e in EMOCOES}
        info["emocao_media_dominante"] = max(dom, key=dom.get) if dom else "-"

        with PdfPages(out_path) as pdf:
            import matplotlib.pyplot as plt
            fig = plt.figure(figsize=(8.27, 11.69)); plt.axis("off")
            y=0.9
            plt.text(0.5,y,titulo,ha="center",va="center",fontsize=20,weight="bold"); y-=0.08
            plt.text(0.5,y,f"Período: {info['inicio']} — {info['fim']}  |  Leituras: {info['leituras']}",
                     ha="center",va="center",fontsize=11); y-=0.06
            plt.text(0.5,y,f"Emoção média dominante: {info['emocao_media_dominante']}",
                     ha="center",va="center",fontsize=12); y-=0.1
            linhas=[]
            for e in EMOCOES:
                v=info.get(f"media_{e}")
                if v is not None: linhas.append([e,f"{v:.2f}"])
            for r in ["cpu","memoria","disco"]:
                v=info.get(f"media_{r}")
                if v is not None: linhas.append([r,f"{v:.2f}%"])
            if linhas:
                table=plt.table(cellText=linhas,colLabels=["Métrica","Média"],loc="center",cellLoc="center")
                table.scale(1,1.5)
            pdf.savefig(fig,bbox_inches="tight"); plt.close(fig)

            fig = plt.figure(figsize=(11.69,8.27))
            medias=[df[e].mean() if e in df.columns else 0 for e in ["feliz","triste","medo","raiva","desgosto","surpresa","neutro"]]
            plt.bar(["feliz","triste","medo","raiva","desgosto","surpresa","neutro"], medias)
            plt.title("Distribuição média de emoções"); plt.ylabel("Média (%)"); plt.xlabel("Emoções")
            pdf.savefig(fig,bbox_inches="tight"); plt.close(fig)

            fig = plt.figure(figsize=(11.69,8.27))
            for e in ["feliz","triste","medo","raiva","desgosto","surpresa","neutro"]:
                if e in df.columns: plt.plot(df["data_hora"], df[e], label=e)
            plt.title("Séries temporais — Emoções"); plt.xlabel("Tempo"); plt.ylabel("Intensidade (%)"); plt.legend(); plt.tight_layout()
            pdf.savefig(fig,bbox_inches="tight"); plt.close(fig)

            fig = plt.figure(figsize=(11.69,8.27))
            for r in ["cpu","memoria","disco"]:
                if r in df.columns: plt.plot(df["data_hora"], df[r], label=r)
            plt.title("Séries temporais — Recursos do sistema"); plt.xlabel("Tempo"); plt.ylabel("Uso (%)"); plt.legend(); plt.tight_layout()
            pdf.savefig(fig,bbox_inches="tight"); plt.close(fig)

        return out_path
    except Exception as e:
        alert("Relatório", f"Falha ao gerar PDF: {e}")
        return None


# ===== PARÂMETROS =====
INTERVALO = 10           # coleta a cada 10s
TEST_DURATION_MIN = 30   # duração do teste em minutos


if __name__ == "__main__":
    email = pedir_email()
    if not email or not email_valido(email):
        alert_erro("E-mail inválido", "Informe um e-mail válido para iniciar.")
        sys.exit(0)

    lic = checar_trial_por_email(email)
    if lic is None:
        alert_erro("Usuário não cadastrado", "E-mail não encontrado. Contate o administrador do sistema.")
        sys.exit(0)

    ativo = (str(lic.get("ativo") or "N").upper() == "S")
    expira = lic.get("expires_at")

    if expira is not None:
        agora = _now_like(expira)
        if agora > expira:
            alert_erro("Licença expirada",
                       f"Sua licença expirou em {_fmt_dt(expira)}. Contate o administrador do sistema.")
            sys.exit(0)

    if not ativo:
        alert_erro("Licença inativa", "Licença trial inativa. Contate o administrador do sistema.")
        sys.exit(0)

    # Autorizado
    csv_path = caminho_csv_na_area_de_trabalho(email)
    preparar_csv(csv_path)
    alert("Autorizado", f"Licença validada. A coleta será feita por {TEST_DURATION_MIN} minutos.")

    inicio = datetime.now()
    fim = inicio + timedelta(minutes=TEST_DURATION_MIN)

    # ==== INICIALIZA WEBCAM ====
    cap = None
    try:
        cap = init_camera()
    except Exception as e:
        alert_erro("Webcam", f"Não foi possível acessar a câmera: {e}")
        sys.exit(0)

    try:
        while datetime.now() <= fim:
            agora = datetime.now()
            try:
                # COLETA REAL
                emocoes = coletar_emocoes_reais(cap)
                recursos = coletar_recursos()
                append_csv(csv_path, agora, emocoes, recursos)
            except Exception as e:
                print(f"[WARN] Falha na coleta: {e}")
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass

        pdf_path = gerar_pdf_relatorio(
            csv_path,
            out_path=caminho_pdf_na_area_de_trabalho(email),
            titulo=f"Relatório Trial — {email}"
        )
        if pdf_path:
            alert("Encerrado", f"Coleta finalizada.\nCSV: {csv_path}\nPDF: {pdf_path}")
        else:
            alert("Encerrado", f"Coleta finalizada. Dados salvos em:\n{csv_path}")
        sys.exit(0)
