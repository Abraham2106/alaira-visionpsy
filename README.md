# Alaira VisionPsy

Monitoreo local de posibles caídas con la webcam o cámaras de celulares. Usa MediaPipe y reglas temporales para estimar posturas, permite delimitar zonas y registra eventos. Los avisos a familiares por Telegram son opcionales. El video permanece en la PC; no se graba por defecto. VisionPsy-Nano está desactivado.

## Empezar en Windows

Necesitas Windows 10/11 **x64**, una webcam y conexión a internet para la primera preparación. No necesitas instalar Python o Node manualmente ni ejecutar como administrador.

Haz doble clic en **`run.cmd`**, o abre una terminal en la carpeta y ejecuta:

```powershell
.\run.cmd
```

El lanzador descarga herramientas portables si faltan, prepara Python 3.12 y las dependencias fijadas, descarga y verifica MediaPipe, crea la credencial interna y abre **http://127.0.0.1:5175**. La primera ejecución puede tardar unos minutos; las siguientes reutilizan lo instalado. Acepta el permiso de cámara al pulsar **Iniciar cámara**.

Mantén abierta la ventana del lanzador. **Ctrl+C** detiene los servicios. Ejecutarlo otra vez mientras esa sesión está activa abre la misma app sin iniciar procesos duplicados.

Las herramientas se guardan en `.tools/`, el entorno Python en `.venv/` y la interfaz en `frontend/node_modules/`. Las descargas portables de [uv](https://github.com/astral-sh/uv) y [Node.js](https://nodejs.org/) se verifican por SHA-256. No se instalan herramientas globales ni se modifica el almacén de certificados.

## Usar la cámara del celular

Con la PC y el teléfono en la misma Wi-Fi:

```powershell
.\run.cmd -Phone
```

El lanzador detecta la IP local, prepara HTTPS y abre las instrucciones de conexión. La **primera vez debes instalar y confiar en el certificado público local en la PC y el celular**: el navegador exige HTTPS confiable para permitir la cámara. Ese paso del sistema operativo no se puede completar automáticamente desde la página.

Después abre **Conexiones → Generar QR de cámara**, escanea el QR con el teléfono y pulsa **Iniciar cámara**. El QR incluye un código temporal de un solo uso; no hay que escribir el token administrador. Mantén la página del teléfono visible.

Si tienes varias interfaces de red, puedes elegir la IP:

```powershell
.\run.cmd -Phone -HostAddress 192.168.1.20
```

Solo se publica el certificado **público** en el puerto 8765; las claves privadas permanecen en `certs/`. Si cambia la IP o vence el certificado, el lanzador prepara otro y debes confiar en el nuevo. No expongas los puertos a internet; algunas redes Wi-Fi aíslan los dispositivos y bloquean la conexión.

## Configurar Telegram

1. En **Conexiones → Familiares**, abre BotFather, crea tu bot y pega su token en el campo protegido.
2. Pulsa **Conectar bot** y luego **Vincular familiar**. El familiar abre el enlace o QR y pulsa **Iniciar** en Telegram.
3. Usa **Enviar prueba** para verificar la recepción. Puedes agregar un contacto principal y otro de respaldo.

La configuración se guarda solo en esta PC y se activa sin reiniciar. Telegram recibe texto, nunca las imágenes. El bot necesita internet; el monitoreo necesita que la PC permanezca encendida. Cambiar a otro bot requiere volver a vincular a los familiares.

## Uso y datos

- **Monitor:** cámaras, estado y eventos. **Cámara de PC:** iniciar o detener la webcam.
- **Zonas:** delimitar camas, sillas u otras áreas. Una zona no demuestra ausencia de riesgo.
- **Conexiones:** agregar cámaras y configurar familiares. Cada cámara conserva su vínculo y sus propias zonas.
- **Historial:** consultar y atender los eventos registrados. Las alertas de caída se consolidan por habitación; las interrupciones técnicas son por cámara.

Eventos, zonas y contactos se guardan en `data/visionpsy.sqlite3`; la configuración del bot está junto a esa base de datos. La credencial interna está en `backend/.env`. Esos archivos, los certificados, modelos y logs están excluidos de Git. Los eventos resueltos se conservan 7 días por defecto. Ajustes: `backend/config.yaml`.

## Comprobación y desarrollo

Preparar y comprobar todo sin dejar servicios corriendo:

```powershell
.\run.cmd -Check
```

Si los puertos predeterminados están ocupados por otra aplicación:

```powershell
.\run.cmd -FrontPort 5176 -BackPort 8003
```

Para trabajar en el código, después de la preparación:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

El supervisor también puede ejecutarse directamente con `python scripts/run_local.py --mode real`. Los logs de arranque están en `reports/local-backend.log` y `reports/local-frontend.log`.

## Alcance actual

Es un MVP experimental para una habitación y una persona supervisada, no un dispositivo médico. Las reglas combinan postura, giro, descenso y persistencia; una pose ausente aparece como **No evaluable**. Los umbrales todavía requieren validación: en la comparación exploratoria de cuatro clips URFD, el detector omitió las dos caídas y no alertó en los dos clips cotidianos. Las pruebas automáticas verifican el funcionamiento del software, no una precisión clínica ni la detección de todas las caídas.
