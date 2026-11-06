# Alaira VisionPsy

Prototipo de monitoreo local de posibles caídas. Usa la webcam o la cámara de un celular conectado a la misma red, estima la postura con MediaPipe y muestra video con esqueleto corporal. Permite marcar zonas, guardar eventos y avisar por Telegram a familiares vinculados.

El video y la inferencia permanecen en la PC. Telegram recibe únicamente texto del evento y necesita internet. Pensado para una habitación y una persona, con una o varias cámaras fijas (ver *Varias cámaras*).

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

### Varias cámaras

Una habitación puede tener varias cámaras (máximo `cameras.max` en `backend/config.yaml`, 4 por defecto). Se agregan y quitan en **Conexiones → Cámaras de la habitación**; `cam-1` es la principal y no se puede quitar. Cada cámara tiene su propio código de vinculación, su credencial, sus zonas (editor de **Zonas**) y su estimador de pose. El monitor muestra un mosaico con una baldosa por cámara cuando hay más de una.

- **Una alerta de caída por habitación.** Se abre cuando cualquier cámara detecta una posible caída y registra qué cámaras la vieron. Se resuelve solo cuando todas las cámaras con pose utilizable vuelven a estar bien; una cámara sin pose, atrasada o desconectada no impide resolver ni genera una caída. Las interrupciones técnicas (cámara desconectada) siguen siendo una alerta por cámara.
- **Compatibilidad.** Sin configuración adicional todo funciona como una sola cámara `cam-1`: las rutas históricas (`/zones`, `/pairing/camera`, `/camera/pair`) y los eventos y zonas ya guardados siguen válidos. Las migraciones de SQLite son idempotentes.
- **Límites conocidos.** No se anota el caso en que dos cámaras discrepan (una ve caída y otra no): prevalece la crítica. Aún no hay interfaz para renombrar una cámara. Hasta tener mediciones en esta PC no se promete más de 2 a 4 cámaras: `scripts/benchmark_cameras.py` mide latencia, CPU y memoria con 1 a 4 estimadores (ver más abajo).
- **Privacidad.** Igual que con una cámara: no se graba video, los eventos no llevan imágenes y Telegram recibe solo texto.

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

Las pruebas de varias cámaras (consolidación, API de cámaras, almacenamiento, WebSocket y mosaico) usan poses y credenciales sintéticas. Para medir cuántas cámaras soporta tu equipo con MediaPipe real:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_cameras.py --image foto_con_persona.jpg --seconds 30
.\.venv\Scripts\python.exe scripts/benchmark_cameras.py --mode processes --max-cameras 3
```

Imprime una línea JSON por cada N (p50/p95 de latencia, % de inferencias sobre 200 ms, CPU y memoria; CPU y memoria requieren `psutil`). Sin `--image` usa un cuadro sin persona y puede subestimar la latencia real.

Las pruebas de reglas y del bot usan datos/proveedores sintéticos: no prueban precisión clínica ni recepción en un celular real. MediaPipe real y WSS se comprobaron por separado en una sesión local de dos minutos. Queda pendiente la aceptación física del teléfono, red y cuenta Telegram.

Estado de validación de varias cámaras: con Python 3.12 pasan las 150 pruebas del backend, las 34 de Vitest y `npm run build`. Benchmark con MediaPipe real (Ryzen 5 8645HS, 12 hilos, hilos, 5 FPS por cámara, 30 s por N, una foto fija con una persona visible, modelo lite): con 1, 2, 3 y 4 estimadores el p95 fue de 42, 38, 36 y 55 ms, 0 % de inferencias sobre 200 ms, 5 FPS sostenidos por cámara y CPU media de 16 %, 28 %, 41 % y 77 % (100 % = un núcleo). Límites de esa medición: una imagen estática, no una escena en movimiento ni una webcam real; no incluye decodificar el JPEG que llega por red, ni las reglas de riesgo, SQLite o el WebSocket que corren en el mismo proceso; el RSS muestreado es irregular y no es fiable; no se probó `--mode processes`. En esta PC 4 cámaras a 5 FPS tienen margen de latencia, pero la CPU llega a 77 % de un núcleo; otro equipo puede dar otro resultado. Prueba física con dos dispositivos (webcam de la PC y un celular por HTTPS en la misma Wi-Fi, una persona que aceptó participar): se confirmaron persona de pie sin alerta, una sola alerta de caída con ambas cámaras, resolución al levantarse, caída vista con una cámara tapada, alerta técnica solo de la cámara detenida y su resolución al reconectar. Sin medir tiempos ni CPU durante esa prueba, y solo con 2 cámaras: 3 o 4 cámaras físicas siguen sin probarse. Telegram, con un bot real y un celular: se confirmó la vinculación con `/start <código>` y que el aviso inicial y el recordatorio a los 60 s llegan. Siguen pendientes de comprobar físicamente que dos cámaras viendo la misma caída producen un único mensaje, que los botones *Estoy atendiendo* y *Descartar* actualizan el evento y la escalada al contacto de respaldo. Python 3.14 no sirve: no hay paquetes de MediaPipe 0.10.21 y algunas pruebas con `TestClient` se cuelgan; usa 3.11 o 3.12.

### VisionPsy-Nano Flash (opcional)

Añade una descripción visual al evento mediante el fork local de llama.cpp de QVAC. El riesgo y las alertas siguen dependiendo de MediaPipe y las reglas. El backend predeterminado `stub` devuelve texto marcado como sintético.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-visionpsy.txt -r requirements-visionpsy-download.txt
.\.venv\Scripts\python.exe scripts/download_visionpsy.py
.\scripts\build_visionpsy_server.ps1
```

El build Windows requiere Visual Studio 2022 Community con MSVC 14.44.35207, CMake/Ninja y CUDA Toolkit 13.1.2 en `models/visionpsy-nano-flash/cuda-13.1.2/` (prefijo local de micromamba, paquete `cuda-toolkit=13.1.2`, canal `nvidia/label/cuda-13.1.2`). Compila para GPU NVIDIA con capacidad 8.6; otras GPU requieren ajustar el script. Fuente y pesos tienen revisiones fijas y se guardan fuera de Git.

En `backend/config.yaml`, configura `models.vision` y reinicia:

```yaml
  vision:
    backend: visionpsy
    gguf_path: ../models/visionpsy-nano-flash/visionpsy-nano-460m-flash-q4_k_m-imat.gguf
    runtime_library_dirs: [../models/visionpsy-nano-flash/cuda-13.1.2/Library/bin]
    timeout_seconds: 15
```

El proyector y ejecutable tienen rutas predeterminadas en ese mismo directorio; se pueden cambiar con `mmproj_path` y `executable`. El servidor se carga una vez, escucha en loopback con clave efímera y admite una consulta a la vez, sin guardar imágenes. Un error o timeout deja la alerta vigente. La prueba del agente con una ilustración sintética registró 0.53 s en RTX 2050; la prueba CPU anterior tardó 45–48 s. Son pruebas técnicas pequeñas, sin demostrar precisión para caídas ni utilidad clínica; el español observado fue deficiente.
