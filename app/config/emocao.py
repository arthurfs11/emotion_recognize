# app/services/emocao.py
from deepface import DeepFace
import cv2
import numpy as np

def detectar_rosto(img_path: str) -> bool:
    """Retorna True se DeepFace/RetinaFace detectar rosto."""
    try:
        dets = DeepFace.extract_faces(img_path=img_path, detector_backend='retinaface', enforce_detection=False)
        return len(dets) > 0
    except Exception:
        return False

def obter_embedding(img_path: str, model_name: str = "Facenet512"):
    """
    Retorna embedding como np.array(float32).
    model_name exemplos: 'Facenet512', 'ArcFace', 'VGG-Face'
    """
    rep = DeepFace.represent(
        img_path=img_path,
        model_name=model_name,
        detector_backend="retinaface",
        enforce_detection=False
    )
    # DeepFace.represent pode retornar lista de dicionários
    if isinstance(rep, list) and len(rep) > 0 and "embedding" in rep[0]:
        return np.array(rep[0]["embedding"], dtype="float32")
    # fallback caso venha diretamente um vetor
    return np.array(rep, dtype="float32")

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 - cosine similarity (0 = idêntico, ~2 = opostos)."""
    a = a.astype("float32"); b = b.astype("float32")
    na = np.linalg.norm(a) + 1e-8
    nb = np.linalg.norm(b) + 1e-8
    return float(1.0 - (a @ b) / (na * nb))

def mesma_pessoa(emb_ref, emb_now, limiar: float = 0.30):
    """
    Retorna (is_same, dist). Quanto menor a dist, mais parecido.
    limiar ~0.3 é um ponto de partida. Calibre com seus dados.
    """
    dist = cosine_distance(emb_ref, emb_now)
    return (dist <= limiar, dist)

def analisar_emocao(img_path: str) -> dict:
    """Retorna dicionário de emoções em PT-BR (raiva, desgosto, medo, feliz, triste, surpresa, neutro)."""
    emocao_dict = {
        "angry": "raiva", "disgust": "desgosto", "fear": "medo",
        "happy": "feliz", "sad": "triste", "surprise": "surpresa", "neutral": "neutro"
    }
    r = DeepFace.analyze(img_path=img_path, actions=['emotion'], enforce_detection=False)
    emo = r[0]["emotion"] if isinstance(r, list) else r["emotion"]
    return {emocao_dict.get(k, k): float(v) for k, v in emo.items()}

def medir_brilho_nitidez(img_path: str):
    """
    Retorna (brilho_medio, nitidez_laplace).
    brilho: média dos níveis em escala de cinza (0-255).
    nitidez: variância do Laplaciano (quanto maior, mais foco).
    """
    img = cv2.imread(img_path)
    if img is None:
        return None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    brilho = float(np.mean(gray))
    nitidez = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return brilho, nitidez
