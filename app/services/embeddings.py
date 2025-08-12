import json
import psycopg2
from config.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

def _conn():
    return psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        host=DB_HOST, port=DB_PORT
    )

def salvar_embedding_db(pessoa_id: str, emb_array) -> None:
    """emb_array: numpy array (ou list) com floats."""
    emb_list = emb_array.tolist() if hasattr(emb_array, "tolist") else list(emb_array)
    conn = _conn(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO pessoas (pessoa_id, embedding)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (pessoa_id)
        DO UPDATE SET embedding = EXCLUDED.embedding
    """, (pessoa_id, json.dumps(emb_list)))
    conn.commit(); cur.close(); conn.close()

def carregar_embedding_db(pessoa_id: str):
    import numpy as np
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT embedding FROM pessoas WHERE pessoa_id=%s", (pessoa_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if row and row[0]:
        return np.array(row[0], dtype="float32")  # psycopg2 já decodifica JSONB -> list
    return None
