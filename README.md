# Alaira VisionPsy

Prototipo de monitoreo local de posibles caídas. Usa la webcam o la cámara de un celular conectado a la misma red, estima la postura con MediaPipe y muestra video con esqueleto corporal. Permite marcar zonas, guardar eventos y avisar por Telegram a familiares vinculados.

El video y la inferencia permanecen en la PC. Telegram recibe únicamente texto del evento y necesita internet. Pensado para una habitación, una persona y una cámara fija.

> Prototipo experimental, no dispositivo médico ni servicio de emergencias. Puede omitir situaciones o producir falsas alertas. Requiere consentimiento de la persona supervisada. Una zona de cama o silla no demuestra ausencia de riesgo.

## Requisitos

- Python 3.11 o 3.12 y Node.js 22.12 o posterior.
- Webcam; para celular, ambos equipos en la misma red y HTTPS confiable.
- Internet para instalar dependencias y descargar el modelo una vez.
- OpenSSL para generar certificados locales. Telegram es opcional y requiere un bot propio.

## Instalación

Desde la raíz, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-pose.lock.txt
.\.venv\Scripts\python.exe scripts/download_pose_model.py
npm --prefix frontend ci
```

Crea `backend/.env` a partir de `backend/.env.example` y asigna un `APP_TOKEN` aleatorio. No sobrescribas un archivo existente. Puedes generar el valor con:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Ejecutar

```powershell
.\.venv\Scripts\python.exe scripts/run_local.py --mode real
```

Abre **http://127.0.0.1:5175** e ingresa el `APP_TOKEN` configurado. El supervisor inicia frontend y backend, comprueba su salud y los detiene con `Ctrl+C`. El backend escucha únicamente en loopback. `--check` valida la configuración sin iniciar servicios; `--mode demo` usa poses sintéticas, sin analizar la imagen.

La configuración está en `backend/config.yaml`; eventos, zonas y avisos se guardan en `data/visionpsy.sqlite3`. La retención predeterminada de eventos resueltos es de 7 días. No se graba video.

### Cámara del celular

Sustituye la IP por la dirección privada real de la PC:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_https.py --host 192.168.1.20 --output certs/demo
.\.venv\Scripts\python.exe scripts/run_local.py --mode real --host 192.168.1.20 --cert-dir certs/demo
```

En el teléfono de pruebas, instala conscientemente **solo `certs/demo/ca.pem`** como CA de desarrollo y abre `https://192.168.1.20:5175`. Las claves privadas permanecen en la PC. Si cambia la IP, prepara un certificado nuevo en otro directorio; no ignores errores de confianza.

En **Conexiones**, ajusta la dirección del QR y genera un código de cámara. Ábrelo en el teléfono, canjea el código y acepta el permiso y consentimiento. Mantén la página visible. Detener libera la cámara; desvincular revoca su credencial. Las redes que aíslan clientes pueden impedir la conexión. No expongas estos puertos a internet.

### Telegram

Guarda `TELEGRAM_BOT_TOKEN` en `backend/.env` y activa `notifications.enabled` en `backend/config.yaml`. Reinicia el servidor. En **Conexiones**, ingresa el usuario del bot y genera un código para el contacto principal o de respaldo. Cada familiar debe iniciar la conversación privada con ese código.

El principal recibe el aviso inicial; si nadie atiende, tras `notifications.reminder_seconds` recibe un recordatorio y se avisa al respaldo. Los botones **Estoy atendiendo** y **Descartar** actualizan el mismo evento. El polling es saliente: no necesita un webhook ni publicar el backend. “Aceptado por Telegram” no acredita lectura ni ayuda recibida. Un timeout puede dejar incertidumbre de entrega y causar repetición al reintentar.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

`backend/` contiene API, pose, reglas, persistencia y avisos; `frontend/` contiene la interfaz; `scripts/` contiene utilidades de ejecución y verificación; `tests/` contiene pruebas backend. El contrato WebSocket está en `docs/ws.schema.json` y se verifica contra Python y TypeScript.

Las pruebas de reglas y del bot usan datos/proveedores sintéticos: no prueban precisión clínica ni recepción en un celular real. MediaPipe real y WSS se comprobaron por separado en una sesión local de dos minutos. Queda pendiente la aceptación física del teléfono, red y cuenta Telegram.

El análisis visual complementario VisionPsy-Nano está pospuesto: en una prueba local con el servidor oficial y una imagen sintética, las consultas CPU tardaron 45–48 segundos, por encima del plazo de 15 segundos del MVP. El backend visual predeterminado devuelve una respuesta marcada como sintética y no decide ni cancela alertas. No confundirlo con MediaPipe, que sí ejecuta inferencia real en `--mode real`.
