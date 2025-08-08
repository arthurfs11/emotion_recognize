import cv2
import os
import time
from datetime import datetime

def capturar_imagem(pessoa_id):
    pasta_imagens = f"images_{pessoa_id}"
    os.makedirs(pasta_imagens, exist_ok=True)

    cap = cv2.VideoCapture(0)

    for _ in range(5):
        cap.read()
        time.sleep(0.1)

    ret, frame = cap.read()

    if ret and frame is not None and frame.sum() > 1000:
        filename = os.path.join(
            pasta_imagens,
            f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        )
        cv2.imwrite(filename, frame)
        cap.release()
        return filename
    else:
        cap.release()
        raise Exception("Erro ao capturar imagem (imagem vazia ou escura).")
