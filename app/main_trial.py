# app/main_trial.py
import os, sys, time, csv
from datetime import datetime, timedelta
import re
import psutil
import psycopg2
from psycopg2.extras import RealDictCursor

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

NEON_DB_URL = "postgresql://neondb_owner:npg_7Mkvmpwc2tuT@ep-broad-boat-ack6fc3f-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"

try:
    import tkinter as tk
    from tkinter import simpledialog, messagebox
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

def coletar_emocoes_mock():
    return {"feliz":10.0,"triste":5.0,"medo":2.0,"raiva":1.0,"desgosto":0.5,"surpresa":3.0,"neutro":78.5}

def coletar_recursos():
    return {"cpu": psutil.cpu_percent(interval=1),
            "mem": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent}

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
        v = _tk_askstring("Trial - Login", "Digite seu e-mail para iniciar o trial:")
        return (v or "").strip() if v else None
    except Exception:
        try: return input("Digite seu e-mail para iniciar o trial: ").strip()
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

def desativar_trial(email: str):
    """Marca ativo='N' e carimba expires_at=now()."""
    try:
        conn = trial_conn()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE trial_licencas
                   SET ativo = 'N',
                       expires_at = NOW()
                 WHERE email = %s
            """, (email,))
        conn.commit()
        conn.close()
    except Exception as e:
        # Não interrompe o fluxo final — só informa no console
        print(f"[WARN] Falha ao desativar licença de {email}: {e}")

# ---------- CSV/PDF ----------
def caminho_csv_na_area_de_trabalho(email: str) -> str:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(desktop, f"trial_emocoes_{email.replace('@','_').replace('.','_')}.csv")

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

def caminho_pdf_na_area_de_trabalho(email: str) -> str:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(desktop, f"trial_relatorio_{email.replace('@','_').replace('.','_')}.pdf")

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

TRIAL_DURATION_MIN = 30
INTERVALO = 60

if __name__ == "__main__":
    email = pedir_email()
    if not email or not email_valido(email):
        alert_erro("E-mail inválido", "Informe um e-mail válido para iniciar o trial.")
        sys.exit(0)

    lic = checar_trial_por_email(email)
    if lic is None:
        alert_erro("Usuário não cadastrado", "E-mail não encontrado. Contate o administrador do sistema.")
        sys.exit(0)

    ativo = (lic.get("ativo") or "N").upper() == "S"
    expira = lic.get("expires_at")

    if not ativo:
        alert_erro("Licença inativa", "Licença trial expirada ou inativa. Contate o administrador do sistema.")
        sys.exit(0)

    if expira is not None and datetime.now() > expira:
        alert_erro("Licença expirada", "Sua licença trial expirou. Contate o administrador do sistema.")
        sys.exit(0)

    csv_path = caminho_csv_na_area_de_trabalho(email)
    preparar_csv(csv_path)
    alert("Trial autorizado", "Sua licença foi validada. O trial rodará por 30 minutos.")

    inicio = datetime.now()
    fim = inicio + timedelta(minutes=TRIAL_DURATION_MIN)

    try:
        while datetime.now() <= fim:
            agora = datetime.now()
            try:
                emocoes = coletar_emocoes_mock()
                recursos = coletar_recursos()
                append_csv(csv_path, agora, emocoes, recursos)
            except Exception:
                pass
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        pass
    finally:
        # GARANTE desativação mesmo com erro/interrupt
        desativar_trial(email)

    pdf_path = gerar_pdf_relatorio(
        csv_path,
        out_path=caminho_pdf_na_area_de_trabalho(email),
        titulo=f"Relatório Trial — {email}"
    )
    if pdf_path:
        alert("Trial finalizado", f"Seu trial terminou.\nCSV: {csv_path}\nPDF: {pdf_path}")
    else:
        alert("Trial finalizado", f"Seu trial terminou. Os dados foram salvos em:\n{csv_path}")
    sys.exit(0)
