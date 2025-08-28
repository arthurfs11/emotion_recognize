from app.services.alerts_engine import _notify_mac  # já está no arquivo
print("Enviando notificação de teste…")
ok = _notify_mac("WellMe (teste)", "Se você vê isso, o banner está funcionando.")
print("ok =", ok)
