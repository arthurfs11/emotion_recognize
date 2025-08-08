import psycopg2
from config.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from config.utils import gerar_pessoa_id
from config.log import *

def salvar_em_banco(emocoes, recursos, data_captura, pessoa_id="anonimo"):
    if pessoa_id is None:
        pessoa_id = gerar_pessoa_id()

    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = conn.cursor()

        dominante = max(emocoes, key=emocoes.get) if emocoes else "usuario_ausente"

        query = """
            INSERT INTO leituras_emocionais (
                pessoa_id, data_captura, raiva, desgosto, medo, feliz, triste, surpresa, neutro, emocao_dominante, cpu, memoria, disco
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        valores = (
            pessoa_id,
            data_captura,
            emocoes.get("raiva", 0) if emocoes else 0,
            emocoes.get("desgosto", 0) if emocoes else 0,
            emocoes.get("medo", 0) if emocoes else 0,
            emocoes.get("feliz", 0) if emocoes else 0,
            emocoes.get("triste", 0) if emocoes else 0,
            emocoes.get("surpresa", 0) if emocoes else 0,
            emocoes.get("neutro", 0) if emocoes else 0,
            dominante,
            recursos["cpu"],
            recursos["mem"],
            recursos["disk"]
        )

        cursor.execute(query, valores)
        conn.commit()
        cursor.close()
        conn.close()
        logger.success(f"✅ [{data_captura.strftime('%H:%M:%S')}] Registro salvo — Estado: {dominante}")
    except Exception as e:
        logger.warning(f"❌ Erro ao salvar no banco: {e}")
