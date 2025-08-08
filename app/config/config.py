from decouple import config

# Configuração do Banco de Dados
DB_NAME = config("DB_NAME", default="emocional")
DB_USER = config("DB_USER", default="arthurfaria")
DB_PASSWORD = config("DB_PASSWORD", default="")
DB_HOST = config("DB_HOST", default="localhost")
DB_PORT = config("DB_PORT", default="5432")

# Intervalo entre capturas (segundos)
TEMPO_CAPTURA = config("TEMPO_CAPTURA", cast=int, default=10)
