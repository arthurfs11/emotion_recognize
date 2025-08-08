from deepface import DeepFace

emocao_dict = {
    "angry": "raiva",
    "disgust": "desgosto",
    "fear": "medo",
    "happy": "feliz",
    "sad": "triste",
    "surprise": "surpresa",
    "neutral": "neutro"
}

def analisar_emocao(imagem_path):
    resultado = DeepFace.analyze(img_path=imagem_path, actions=['emotion'], enforce_detection=False)
    emocao = resultado[0]["emotion"]
    emocao_traduzida = {emocao_dict.get(k, k): v for k, v in emocao.items()}
    return emocao_traduzida
