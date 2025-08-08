from datetime import datetime
import time

from config.utils import gerar_pessoa_id
from config.monitor import esta_usando_computador
from config.camera import capturar_imagem
from config.emocao import analisar_emocao
from config.recursos import coletar_recursos
from config.database import salvar_em_banco
from config.config import TEMPO_CAPTURA
from config.log import *

if __name__ == "__main__":
    logger.info("🟢 Iniciando o monitoramento emocional...")

    logger.debug("Carregando o id da pessoa...")
    pessoa_id = gerar_pessoa_id()
    logger.debug(f"ID da pessoa gerado: {pessoa_id}")

    while True:
        try:    
            logger.debug("Iniciando captura de dados emocionais...")
            data_captura = datetime.now()
            recursos = coletar_recursos()
            logger.debug(f"Recursos coletados: {recursos}")

            if esta_usando_computador():
                imagem = capturar_imagem(pessoa_id)
                emocoes = analisar_emocao(imagem)
            else:
                logger.warning(f"🕒 [{data_captura.strftime('%H:%M:%S')}] Usuário ausente — capturando apenas recursos.")
                emocoes = None

            salvar_em_banco(emocoes, recursos, data_captura, pessoa_id)

        except Exception as erro:
            logger.warning(f"❌ Erro na execução: {erro}")

        time.sleep(TEMPO_CAPTURA)
