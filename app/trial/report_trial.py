import argparse, os
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

EMOCOES = ["feliz","triste","medo","raiva","desgosto","surpresa","neutro"]

def load_csv(path):
    df = pd.read_csv(path)
    # garante datetime
    df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce")
    df = df.sort_values("data_hora").reset_index(drop=True)
    return df

def resumo_metricas(df):
    out = {}
    out["leituras"] = len(df)
    out["inicio"]   = df["data_hora"].min()
    out["fim"]      = df["data_hora"].max()
    for c in EMOCOES + ["cpu","memoria","disco"]:
        if c in df.columns:
            out[f"media_{c}"] = float(df[c].mean())
    # emoção dominante média
    dom = {e: out.get(f"media_{e}", 0.0) for e in EMOCOES}
    out["emocao_media_dominante"] = max(dom, key=dom.get) if dom else None
    return out

def pagina_capa(pdf, titulo, info):
    fig = plt.figure(figsize=(8.27, 11.69))  # A4 vertical
    plt.axis("off")
    y = 0.9
    plt.text(0.5, y, titulo, ha="center", va="center", fontsize=20, weight="bold")
    y -= 0.08
    subt = f"Período: {info['inicio']} — {info['fim']}  |  Leituras: {info['leituras']}"
    plt.text(0.5, y, subt, ha="center", va="center", fontsize=11)
    y -= 0.06
    emo_dom = info.get("emocao_media_dominante") or "-"
    plt.text(0.5, y, f"Emoção média dominante: {emo_dom}", ha="center", va="center", fontsize=12)
    y -= 0.1

    # Tabela simples de médias
    linhas = []
    for e in EMOCOES:
        v = info.get(f"media_{e}")
        if v is not None:
            linhas.append([e, f"{v:.2f}"])
    for r in ["cpu","memoria","disco"]:
        v = info.get(f"media_{r}")
        if v is not None:
            linhas.append([r, f"{v:.2f}%"])

    if linhas:
        col_labels = ["Métrica","Média"]
        table = plt.table(cellText=linhas, colLabels=col_labels, loc="center", cellLoc="center")
        table.scale(1, 1.5)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

def graf_emocoes_barras(pdf, df):
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 horizontal
    medias = [df[e].mean() if e in df.columns else 0 for e in EMOCOES]
    plt.bar(EMOCOES, medias)
    plt.title("Distribuição média de emoções")
    plt.ylabel("Média (%)")
    plt.xlabel("Emoções")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

def graf_emocoes_series(pdf, df):
    fig = plt.figure(figsize=(11.69, 8.27))
    for e in EMOCOES:
        if e in df.columns:
            plt.plot(df["data_hora"], df[e], label=e)
    plt.title("Séries temporais — Emoções")
    plt.xlabel("Tempo")
    plt.ylabel("Intensidade (%)")
    plt.legend()
    plt.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

def graf_recursos_series(pdf, df):
    fig = plt.figure(figsize=(11.69, 8.27))
    for r in ["cpu","memoria","disco"]:
        if r in df.columns:
            plt.plot(df["data_hora"], df[r], label=r)
    plt.title("Séries temporais — Recursos do sistema")
    plt.xlabel("Tempo")
    plt.ylabel("Uso (%)")
    plt.legend()
    plt.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Caminho do CSV gerado pelo trial")
    parser.add_argument("--out", required=False, help="Caminho do PDF de saída")
    parser.add_argument("--titulo", default="Relatório Trial")
    args = parser.parse_args()

    df = load_csv(args.csv)
    info = resumo_metricas(df)

    out = args.out or os.path.splitext(args.csv)[0] + "_relatorio.pdf"
    with PdfPages(out) as pdf:
        pagina_capa(pdf, args.titulo, info)
        graf_emocoes_barras(pdf, df)
        graf_emocoes_series(pdf, df)
        graf_recursos_series(pdf, df)

    print(f"OK! Relatório salvo em: {out}")

if __name__ == "__main__":
    main()
