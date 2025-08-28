# app/services/telemetria.py
from services.alerts_storage import PostgresStorage
from services.alerts_engine import AlertManager
from config.database import salvar_em_banco

_storage = PostgresStorage()
_alerts = AlertManager(_storage)

def registrar_amostra(emocoes, recursos, data_captura, pessoa_id, meta=None, user_id="default"):
    # 1) salva leitura "bruta"
    salvar_em_banco(emocoes, recursos, data_captura, pessoa_id, meta=meta)
    # 2) processa métrica e possivelmente alerta (também atualiza a linha com stress/z/mu/sigma)
    return _alerts.process_sample(user_id, pessoa_id, data_captura, emocoes, recursos)
