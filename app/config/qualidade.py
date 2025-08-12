# app/config/qualidade.py
import cv2
import numpy as np

def brilho_media_v(bgr_img):
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    return float(np.mean(v))  # 0..255

def nitidez_laplaciano(bgr_img):
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def contraste_gray(bgr_img):
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    return float(gray.std())

def avaliar_qualidade(bgr_img, brilho_min=30.0, nitidez_min=30.0, contraste_min=15.0):
    """
    Retorna (ok, metrics, motivo) onde:
      - ok: bool (True se passou nos limiares)
      - metrics: dict(brilho, nitidez, contraste)
      - motivo: 'ok' | 'escura' | 'borrada' | 'baixo_contraste'
    """
    b = brilho_media_v(bgr_img)
    n = nitidez_laplaciano(bgr_img)
    c = contraste_gray(bgr_img)

    motivo = "ok"
    ok = True
    if b < brilho_min:
        motivo = "escura"; ok = False
    elif n < nitidez_min:
        motivo = "borrada"; ok = False
    elif c < contraste_min:
        motivo = "baixo_contraste"; ok = False

    return ok, {"brilho": b, "nitidez": n, "contraste": c}, motivo
