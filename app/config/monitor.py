import pyautogui
import time

ultima_posicao_mouse = None
tempo_ultimo_movimento = time.time()

def esta_usando_computador():
    global ultima_posicao_mouse, tempo_ultimo_movimento
    pos_atual = pyautogui.position()

    if pos_atual != ultima_posicao_mouse:
        ultima_posicao_mouse = pos_atual
        tempo_ultimo_movimento = time.time()
        return True

    if time.time() - tempo_ultimo_movimento > 60:
        return False
    return True
