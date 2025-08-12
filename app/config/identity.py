# app/config/identity.py
import os
import uuid
from pathlib import Path
import numpy as np
from typing import Optional, Tuple

from config.emocao import obter_embedding, mesma_pessoa
from config.database import listar_pessoas_embeddings, salvar_embedding_db

LIMIAR_COSINE_DEFAULT = 0.30  # ajuste fino depois
STORE_DIR = Path(os.path.expanduser("~/.well"))
STORE_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = STORE_DIR / "pessoa_id"

def gerar_pessoa_id() -> str:
    return str(uuid.uuid4())

def _read_local_id() -> Optional[str]:
    try:
        if STORE_FILE.exists():
            return STORE_FILE.read_text().strip()
    except Exception:
        pass
    return None

def _write_local_id(pid: str) -> None:
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(pid)
    except Exception:
        pass

def _match_db_by_embedding(emb_now: np.ndarray, limiar: float) -> Optional[Tuple[str, float]]:
    """
    Percorre embeddings do banco e retorna (pessoa_id, dist) do melhor match <= limiar.
    """
    candidatos = listar_pessoas_embeddings()  # [(pessoa_id, np.array), ...]
    best_id, best_dist = None, 1e9
    for pid, emb in candidatos:
        # cosine distance já embutida dentro de mesma_pessoa; aqui reaproveitamos cálculo
        # mas precisamos só da distância
        a = emb.astype("float32")
        b = emb_now.astype("float32")
        na = np.linalg.norm(a) + 1e-8
        nb = np.linalg.norm(b) + 1e-8
        dist = float(1.0 - (a @ b) / (na * nb))
        if dist < best_dist:
            best_dist, best_id = dist, pid

    if best_id is not None and best_dist <= limiar:
        return best_id, best_dist
    return None

def load_or_create_pessoa_id(
    img_path_for_enrollment: Optional[str],
    limiar_cosine: float = LIMIAR_COSINE_DEFAULT
) -> Tuple[str, Optional[np.ndarray], Optional[float], str]:
    """
    Retorna (pessoa_id, emb_now, distancia_usada, origem)
    origem ∈ {"db_match","local_valid","local_no_face","new_id"}
    - Tenta identificar por face via DB.
    - Se falhar, tenta validar o ID local contra o rosto atual (se houver).
    - Se tudo falhar, gera novo ID.
    """
    emb_now = None
    if img_path_for_enrollment:
        try:
            emb_now = obter_embedding(img_path_for_enrollment)
        except Exception:
            emb_now = None

    # 1) Se tenho embedding atual, tento bater com DB
    if emb_now is not None:
        hit = _match_db_by_embedding(emb_now, limiar_cosine)
        if hit:
            pid, dist = hit
            _write_local_id(pid)
            return pid, emb_now, dist, "db_match"

    # 2) Sem match no DB (ou sem embedding): tento o local
    local_id = _read_local_id()
    if local_id:
        if emb_now is not None:
            # valida se o ID local corresponde ao rosto atual (comparando com embedding salvo, se existir)
            # para isso tentamos pegar o embedding do local_id no DB (se existir)
            from config.database import carregar_embedding_db
            emb_ref = carregar_embedding_db(local_id)
            if emb_ref is not None:
                same, dist = mesma_pessoa(emb_ref, emb_now, limiar=limiar_cosine)
                if same:
                    return local_id, emb_now, dist, "local_valid"
                # Se não for a mesma pessoa, caímos para gerar novo ID
            else:
                # Não existe embedding no banco para o local_id -> assumimos local como válido por enquanto
                return local_id, emb_now, None, "local_no_face"
        else:
            # Sem rosto agora (luz ruim, ausência), reaproveita local_id
            return local_id, None, None, "local_no_face"

    # 3) Nada local e sem match: criar novo
    new_id = gerar_pessoa_id()
    _write_local_id(new_id)
    # se tenho emb_now, já salvo como perfil
    if emb_now is not None:
        salvar_embedding_db(new_id, emb_now)
    return new_id, emb_now, None, "new_id"
