# app/main.py
import os, time
from datetime import datetime
import cv2
import psutil
import pyautogui
from config.log import *

from config.identity import load_or_create_pessoa_id
from config.database import (
    ensure_tables, salvar_em_banco, salvar_embedding_db, carregar_embedding_db
)
from config.emocao import (
    detectar_rosto, obter_embedding, analisar_emocao, mesma_pessoa, medir_brilho_nitidez
)

# ===== CONSTANTES =====
LIMIAR_COSINE   = 0.30
INTERVALO_BASE  = 10
INTERVALO_MAX   = 60
NITIDEZ_MIN     = 30.0
BRILHO_MIN      = 30.0

# Otimização da captura
CAM_WIDTH       = 640
CAM_HEIGHT      = 480
WARMUP_FRAMES   = 3
WARMUP_SLEEP    = 0.05
JPEG_QUALITY    = 60
JPEG_OPTIMIZE   = True

# Economia agressiva
ECONOMIA_ATIVA        = True
CPU_ALTA_LIMIAR       = 80.0       # % de uso de CPU
RUIM_STREAK_LIMIAR    = 3          # leituras seguidas ruins
COOLDOWN_SEGUNDOS     = 120        # tempo sem capturar imagem
BACKOFF_MULTIPLICADOR = 3          # aumenta o intervalo durante economia

# ===== utils =====
ultima_posicao = None
ultimo_mov = time.time()

def coletar_recursos():
    return {
        "cpu": psutil.cpu_percent(interval=0.5),
        "mem": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent
    }

def esta_usando_computador(timeout=60):
    global ultima_posicao, ultimo_mov
    try:
        pos = pyautogui.position()
    except Exception:
        return True
    if pos != ultima_posicao:
        ultima_posicao = pos
        ultimo_mov = time.time()
        return True
    return (time.time() - ultimo_mov) <= timeout

def _pasta_imgs(pid: str) -> str:
    pasta = f"images_{pid}"
    os.makedirs(pasta, exist_ok=True)
    return pasta

def _abrir_camera_configurada():
    cap = cv2.VideoCapture(0)
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    except Exception:
        pass
    return cap

def capturar_imagem(pessoa_id: str):
    pasta = _pasta_imgs(pessoa_id)
    cap = _abrir_camera_configurada()
    for _ in range(WARMUP_FRAMES):
        cap.read(); time.sleep(WARMUP_SLEEP)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None or frame.sum() < 1000:
        raise RuntimeError("Frame inválido/escuro")
    path = os.path.join(pasta, f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    if JPEG_OPTIMIZE:
        params += [cv2.IMWRITE_JPEG_OPTIMIZE, 1]
    cv2.imwrite(path, frame, params)
    return path

# PT-BR emoções
_MAP_EN_PT = {
    "happy": "feliz", "sad": "triste", "fear": "medo", "angry": "raiva",
    "disgust": "desgosto", "surprise": "surpresa", "neutral": "neutro",
}
def _normalizar_emocoes_pt(emocoes):
    if not emocoes:
        return None
    out = {}
    for k, v in emocoes.items():
        k2 = _MAP_EN_PT.get(k.lower(), k.lower())
        out[k2] = float(v) if v is not None else 0.0
    for k in ["feliz","triste","medo","raiva","desgosto","surpresa","neutro"]:
        out.setdefault(k, 0.0)
    return out

if __name__ == "__main__":
    ensure_tables()

    # Bootstrap identidade
    img_bootstrap = None
    try:
        img_bootstrap = capturar_imagem("bootstrap")
    except Exception:
        img_bootstrap = None

    pessoa_id, emb_now, dist, origem = load_or_create_pessoa_id(
        img_bootstrap, limiar_cosine=LIMIAR_COSINE
    )
    logger.success(f"[IDENTIDADE] pessoa_id={pessoa_id} origem={origem} dist={dist}")

    if emb_now is not None:
        try:
            salvar_embedding_db(pessoa_id, emb_now)
        except Exception:
            pass
    try:
        if img_bootstrap and os.path.exists(img_bootstrap):
            os.remove(img_bootstrap)
    except Exception:
        pass

    emb_ref = carregar_embedding_db(pessoa_id)

    # ===== Loop principal =====
    intervalo_atual = INTERVALO_BASE
    ruim_streak = 0
    cooldown_ate = 0.0

    while True:
        inicio_ciclo = time.time()
        data_captura = datetime.now()
        recursos = coletar_recursos()
        meta = {
            "camera_status": "ok",
            "face_status": "ok",
            "mesma_pessoa": None,
            "qualidade": None,
            "brilho": None,
            "face_distance": None
        }
        emocoes = None
        img_path = None
        motivo_backoff = None

        # ===== Economia agressiva: checagens antes de abrir a câmera =====
        if ECONOMIA_ATIVA:
            agora = time.time()
            cpu_alta = recursos["cpu"] >= CPU_ALTA_LIMIAR
            em_cooldown = agora < cooldown_ate

            if cpu_alta or em_cooldown or ruim_streak >= RUIM_STREAK_LIMIAR:
                # pula captura e análise nesta rodada
                if cpu_alta:
                    motivo_backoff = "cpu_alta"
                elif em_cooldown:
                    motivo_backoff = "cooldown"
                else:
                    motivo_backoff = "ruim_streak"

                meta["camera_status"] = "economia"
                meta["face_status"]   = "ausente"
                # emocoes = None -> banco marca 'usuario_ausente'
            else:
                # segue o fluxo normal de captura/análise
                try:
                    if esta_usando_computador():
                        img_path = capturar_imagem(pessoa_id)
                        brilho, nitidez = medir_brilho_nitidez(img_path)
                        meta["brilho"] = brilho
                        meta["qualidade"] = nitidez

                        if (brilho is not None and brilho < BRILHO_MIN) or (nitidez is not None and nitidez < NITIDEZ_MIN):
                            meta["camera_status"] = "baixa_qualidade"
                            motivo_backoff = "baixa_qualidade"
                            ruim_streak += 1
                        else:
                            if detectar_rosto(img_path):
                                if emb_ref is None:
                                    try:
                                        emb_ref = obter_embedding(img_path)
                                        salvar_embedding_db(pessoa_id, emb_ref)
                                    except Exception:
                                        emb_ref = None

                                emb_now_loop = obter_embedding(img_path)
                                if emb_ref is None:
                                    meta["mesma_pessoa"] = True
                                    meta["face_distance"] = 0.0
                                    emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                else:
                                    is_same, dist_loop = mesma_pessoa(emb_ref, emb_now_loop, limiar=LIMIAR_COSINE)
                                    meta["mesma_pessoa"] = is_same
                                    meta["face_distance"] = dist_loop
                                    meta["face_status"] = "ok" if is_same else "outra_pessoa"

                                    if is_same:
                                        emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                        ruim_streak = 0  # sucesso zera streak
                                    else:
                                        # Reatribuição automática
                                        pid2, emb2, dist2, origem2 = load_or_create_pessoa_id(
                                            img_path, limiar_cosine=LIMIAR_COSINE
                                        )
                                        if pid2 != pessoa_id:
                                            pessoa_id = pid2
                                            emb_ref = carregar_embedding_db(pessoa_id)
                                            if emb_ref is None and emb2 is not None:
                                                salvar_embedding_db(pessoa_id, emb2)
                                                emb_ref = emb2
                                            meta["face_status"] = f"reatribuido:{origem2}"
                                            meta["face_distance"] = dist2
                                            emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                            ruim_streak = 0
                                        else:
                                            meta["face_status"] = "variacao_rosto"
                                            emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                            ruim_streak = 0
                            else:
                                meta["face_status"] = "ausente"
                                motivo_backoff = "ausente"
                                ruim_streak += 1
                    else:
                        meta["face_status"] = "ausente"
                        meta["camera_status"] = "ok"
                        motivo_backoff = "ausente"
                        ruim_streak += 1
                except Exception:
                    meta["camera_status"] = "erro"
        else:
            # ===== Sem economia agressiva (fluxo anterior) =====
            try:
                if esta_usando_computador():
                    img_path = capturar_imagem(pessoa_id)
                    brilho, nitidez = medir_brilho_nitidez(img_path)
                    meta["brilho"] = brilho
                    meta["qualidade"] = nitidez
                    if (brilho is not None and brilho < BRILHO_MIN) or (nitidez is not None and nitidez < NITIDEZ_MIN):
                        meta["camera_status"] = "baixa_qualidade"
                        motivo_backoff = "baixa_qualidade"
                    else:
                        if detectar_rosto(img_path):
                            if emb_ref is None:
                                try:
                                    emb_ref = obter_embedding(img_path)
                                    salvar_embedding_db(pessoa_id, emb_ref)
                                except Exception:
                                    emb_ref = None
                            emb_now_loop = obter_embedding(img_path)
                            if emb_ref is None:
                                meta["mesma_pessoa"] = True
                                meta["face_distance"] = 0.0
                                emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                            else:
                                is_same, dist_loop = mesma_pessoa(emb_ref, emb_now_loop, limiar=LIMIAR_COSINE)
                                meta["mesma_pessoa"] = is_same
                                meta["face_distance"] = dist_loop
                                meta["face_status"] = "ok" if is_same else "outra_pessoa"
                                if is_same:
                                    emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                else:
                                    pid2, emb2, dist2, origem2 = load_or_create_pessoa_id(
                                        img_path, limiar_cosine=LIMIAR_COSINE
                                    )
                                    if pid2 != pessoa_id:
                                        pessoa_id = pid2
                                        emb_ref = carregar_embedding_db(pessoa_id)
                                        if emb_ref is None and emb2 is not None:
                                            salvar_embedding_db(pessoa_id, emb2)
                                            emb_ref = emb2
                                        meta["face_status"] = f"reatribuido:{origem2}"
                                        meta["face_distance"] = dist2
                                        emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                                    else:
                                        meta["face_status"] = "variacao_rosto"
                                        emocoes = _normalizar_emocoes_pt(analisar_emocao(img_path))
                        else:
                            meta["face_status"] = "ausente"
                            motivo_backoff = "ausente"
                else:
                    meta["face_status"] = "ausente"
                    meta["camera_status"] = "ok"
                    motivo_backoff = "ausente"
            except Exception:
                meta["camera_status"] = "erro"

        # Persistência
        salvar_em_banco(emocoes, recursos, data_captura, pessoa_id, meta)

        # Remove a imagem
        try:
            if img_path and os.path.exists(img_path):
                os.remove(img_path)
        except Exception:
            pass

        # ===== Regras de economia: cooldown e backoff =====
        if ECONOMIA_ATIVA:
            if motivo_backoff in ("ausente", "baixa_qualidade", "cpu_alta", "ruim_streak", "cooldown"):
                # entra/renova cooldown exceto se foi apenas cpu_alta (momentânea)
                if motivo_backoff in ("ausente", "baixa_qualidade", "ruim_streak"):
                    cooldown_ate = max(cooldown_ate, time.time() + COOLDOWN_SEGUNDOS)
                intervalo_atual = min(INTERVALO_BASE * BACKOFF_MULTIPLICADOR, INTERVALO_MAX)
            else:
                # sucesso: zera streak e sai de cooldown
                ruim_streak = 0
                cooldown_ate = 0.0
                intervalo_atual = INTERVALO_BASE
        else:
            intervalo_atual = INTERVALO_BASE if not motivo_backoff else min(INTERVALO_BASE * 3, INTERVALO_MAX)

        gasto = time.time() - inicio_ciclo
        time.sleep(max(0.0, intervalo_atual - gasto))
