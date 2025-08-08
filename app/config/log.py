# app/utils/logger.py
from loguru import logger
from random import randint
import psycopg2
from datetime import datetime
from decouple import config

# Configurações do banco
DB_NAME = config("DB_NAME", default="emocional")
DB_USER = config("DB_USER", default="arthurfaria")
DB_PASSWORD = config("DB_PASSWORD", default="")
DB_HOST = config("DB_HOST", default="localhost")
DB_PORT = config("DB_PORT", default="5432")

ARQUIVO_LOG = "log.txt"
IDENTIFICACAO = randint(10, 100000000)

# Função para inserir log no banco
def salvar_log_no_banco(message):
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO logs_sistema (identificacao, data_hora, nivel, mensagem)
            VALUES (%s, %s, %s, %s)
        """, (
            message.record["extra"]["id"],
            datetime.fromtimestamp(message.record["time"].timestamp()),
            message.record["level"].name,
            message.record["message"]
        ))

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Erro ao salvar log no banco: {e}")

# Configura loguru para arquivo e banco
logger.add(ARQUIVO_LOG, format="{time:DD/MM/YYYY HH:mm:ss} | {level} | {extra[id]} | {message}")
logger.add(salvar_log_no_banco)  # Envia pro banco também
logger = logger.bind(id=IDENTIFICACAO)
