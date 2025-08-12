# app/config/database.py
import json
import psycopg2
from psycopg2.extras import Json
from typing import Any, Dict, Optional

from config.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from config.log import logger

# ---- conjunto permitido (alinhado ao CHECK do banco) ----
PERMITIDAS = {
    "feliz", "triste", "medo", "raiva", "desgosto", "surpresa", "neutro", "usuario_ausente"
}

# ---------- Conexão ----------
def _conn():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )

# ---------- Tabelas (opcional: chame no startup) ----------
def ensure_tables():
    """Cria/ajusta tabelas necessárias (idempotente)."""
    try:
        conn = _conn()
        cur = conn.cursor()

        # Tabela de pessoas (embedding em JSONB)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pessoas (
              pessoa_id   VARCHAR(64) PRIMARY KEY,
              embedding   JSONB NOT NULL,
              created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Colunas extras na leituras_emocionais (se ainda não existirem)
        cur.execute("""
            ALTER TABLE leituras_emocionais
              ADD COLUMN IF NOT EXISTS camera_status VARCHAR(30) DEFAULT 'ok',
              ADD COLUMN IF NOT EXISTS face_status   VARCHAR(30) DEFAULT 'ok',
              ADD COLUMN IF NOT EXISTS mesma_pessoa  BOOLEAN,
              ADD COLUMN IF NOT EXISTS qualidade     REAL,
              ADD COLUMN IF NOT EXISTS brilho        REAL,
              ADD COLUMN IF NOT EXISTS face_distance REAL;
        """)

        conn.commit()
        cur.close()
        conn.close()
        logger.info("Tabelas verificadas/criadas com sucesso.")
    except Exception as e:
        logger.exception(f"Erro ao garantir tabelas: {e}")

# ---------- helpers ----------
def _normalizar_dominante(emocoes: Optional[Dict[str, float]]) -> str:
    """Escolhe a dominante e garante que está no set PERMITIDAS."""
    if not emocoes:
        return "usuario_ausente"
    # pega a chave com maior valor
    dom = max(emocoes, key=emocoes.get)
    dom = (dom or "").strip().lower()
    # alguns modelos/flows podem vir com inglês por engano — mapeia rápido
    mapa_en_pt = {
        "happy": "feliz",
        "sad": "triste",
        "fear": "medo",
        "angry": "raiva",
        "disgust": "desgosto",
        "surprise": "surpresa",
        "neutral": "neutro",
        "usuario_ausente": "usuario_ausente",
    }
    dom = mapa_en_pt.get(dom, dom)
    if dom not in PERMITIDAS:
        dom = "usuario_ausente"
    return dom

# ---------- Embeddings ----------
def salvar_embedding_db(pessoa_id: str, emb_array: Any) -> None:
    """
    Salva/atualiza o embedding de uma pessoa em JSONB.
    emb_array: numpy array OU list de floats.
    """
    try:
        emb_list = emb_array.tolist() if hasattr(emb_array, "tolist") else list(emb_array)
        conn = _conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO pessoas (pessoa_id, embedding)
            VALUES (%s, %s)
            ON CONFLICT (pessoa_id) DO UPDATE
              SET embedding = EXCLUDED.embedding
        """, (pessoa_id, Json(emb_list)))
        conn.commit(); cur.close(); conn.close()
        logger.debug(f"Embedding salvo para pessoa_id={pessoa_id} (len={len(emb_list)})")
    except Exception as e:
        logger.exception(f"Erro ao salvar embedding no banco: {e}")

def carregar_embedding_db(pessoa_id: str):
    """
    Retorna o embedding como numpy array (float32) ou None se não existir.
    """
    try:
        import numpy as np
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT embedding FROM pessoas WHERE pessoa_id=%s", (pessoa_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row[0] is not None:
            return np.array(row[0], dtype="float32")
        return None
    except Exception as e:
        logger.exception(f"Erro ao carregar embedding do banco: {e}")
        return None

# ---------- Leituras (emoções + recursos + metadata) ----------
def salvar_em_banco(
    emocoes: Optional[Dict[str, float]],
    recursos: Dict[str, float],
    data_captura,
    pessoa_id: str,
    meta: Optional[Dict[str, Any]] = None
) -> None:
    """
    meta: {
      camera_status, face_status, mesma_pessoa, qualidade, brilho, face_distance
    }
    """
    meta = meta or {}
    camera_status = meta.get("camera_status", "ok")
    face_status   = meta.get("face_status", "ok")
    mesma_pessoa  = meta.get("mesma_pessoa", None)
    qualidade     = meta.get("qualidade", None)
    brilho        = meta.get("brilho", None)
    face_distance = meta.get("face_distance", None)

    # Dominante saneada para não violar CHECK
    dominante = _normalizar_dominante(emocoes)

    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO leituras_emocionais (
              pessoa_id, data_captura,
              raiva, desgosto, medo, feliz, triste, surpresa, neutro, emocao_dominante,
              cpu, memoria, disco,
              camera_status, face_status, mesma_pessoa, qualidade, brilho, face_distance
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      %s,%s,%s,
                      %s,%s,%s,%s,%s,%s)
        """, (
            pessoa_id, data_captura,
            (emocoes or {}).get("raiva", 0),
            (emocoes or {}).get("desgosto", 0),
            (emocoes or {}).get("medo", 0),
            (emocoes or {}).get("feliz", 0),
            (emocoes or {}).get("triste", 0),
            (emocoes or {}).get("surpresa", 0),
            (emocoes or {}).get("neutro", 0),
            dominante,
            recursos.get("cpu", 0), recursos.get("mem", 0), recursos.get("disk", 0),
            camera_status, face_status, mesma_pessoa, qualidade, brilho, face_distance
        ))
        conn.commit(); cur.close(); conn.close()
        logger.info(f"Registro salvo — pessoa={pessoa_id} estado={dominante} cam={camera_status} face={face_status}")
    except Exception as e:
        logger.exception(f"❌ Erro ao salvar no banco: {e}")

def listar_pessoas_embeddings():
    """
    Retorna lista de (pessoa_id, np.array(float32)) com embeddings existentes.
    """
    import numpy as np
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT pessoa_id, embedding FROM pessoas")
        rows = cur.fetchall()
        cur.close(); conn.close()
        out = []
        for pid, emb in rows:
            if emb is not None:
                out.append((pid, np.array(emb, dtype="float32")))
        return out
    except Exception as e:
        logger.exception(f"Erro ao listar embeddings: {e}")
        return []
