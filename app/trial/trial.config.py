from decouple import config

# Configuração do Banco de Dados
TRIAL_DB_HOST="SEU_IP_PUBLICO"
TRIAL_DB_USER="trial_app"
TRIAL_DB_PASSWORD="SENHA_FORTE_AQUI"
TRIAL_DB_NAME="controle_trial"
TRIAL_DB_PORT=5432
WELLIO_TRIAL_KEY="ABCDEF-123456"


# Intervalo entre capturas (segundos)
TEMPO_CAPTURA = config("TEMPO_CAPTURA", cast=int, default=10)
