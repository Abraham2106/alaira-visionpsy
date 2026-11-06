"""Un único proceso supervisor para backend y frontend locales; Ctrl+C los detiene."""
import argparse
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.config import load_settings
from scripts.prepare_https import host_name


def port_free(host,port):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host,port))
        except OSError as error:
            raise RuntimeError(f"No se puede usar {host}:{port}: puerto ocupado o IP no disponible") from error


def public_certificate_server(host, port, cert_dir, app_url):
    """Expose exactly the public CA and setup help, never a filesystem directory."""
    from html import escape
    public_ca=(Path(cert_dir)/'ca.pem').read_bytes()
    page=(f'<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
          f'<title>VisionPsy · Celular</title><body style="font:16px system-ui;max-width:640px;margin:40px auto;padding:20px">'
          f'<h1>Conectar el celular</h1><ol><li><a href="/ca.crt">Descargar certificado público</a>.</li>'
          f'<li>Confía en ese certificado local en la PC y en el celular. Solo se necesita al preparar esta conexión o renovar su certificado.</li>'
          f'<li><a href="{escape(app_url)}">Abrir VisionPsy</a> y generar el QR en Conexiones.</li></ol>'
          f'<p>Ambos dispositivos deben estar en la misma red. Las claves privadas permanecen en esta PC.</p></body></html>').encode()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/','/ca.crt'):
                self.send_error(404);return
            body=public_ca if self.path=='/ca.crt' else page
            self.send_response(200)
            self.send_header('Content-Type','application/x-x509-ca-cert' if self.path=='/ca.crt' else 'text/html; charset=utf-8')
            if self.path=='/ca.crt':self.send_header('Content-Disposition','attachment; filename="visionpsy-local-ca.crt"')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*_):pass
    server=ThreadingHTTPServer((host,port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def prepare(args):
    host=host_name(args.host)
    # Verify this is an interface of this PC before sending any credential in a reuse probe.
    port_free(host,0)
    if args.front_port==args.back_port:
        raise RuntimeError("Frontend y backend necesitan puertos distintos")
    env=os.environ.copy()
    env.update({"APP_HOST":"127.0.0.1","APP_PORT":str(args.back_port),
                "POSE_BACKEND":"mediapipe" if args.mode=="real" else "stub",
                "BACKEND_URL":f"http://127.0.0.1:{args.back_port}"})
    if args.database:
        env["APP_STORAGE_PATH"]=str(Path(args.database).resolve())
    scheme="http"
    tls_context=None
    if args.cert_dir:
        cert_dir=Path(args.cert_dir).resolve()
        metadata=json.loads((cert_dir/"https.json").read_text(encoding="utf-8"))
        if host not in {metadata["host"],"localhost","127.0.0.1"}:
            raise RuntimeError("El host no coincide con el certificado; prepara uno para esta dirección")
        for name in ["server.pem","server-key.pem","ca.pem"]:
            if not (cert_dir/name).is_file():
                raise RuntimeError(f"Falta certificado local: {name}")
        env.update({"LOCAL_TLS_CERT":str(cert_dir/"server.pem"),"LOCAL_TLS_KEY":str(cert_dir/"server-key.pem")})
        tls_context=ssl.create_default_context(cafile=str(cert_dir/"ca.pem"))
        scheme="https"
    elif host not in {"127.0.0.1","localhost"}:
        raise RuntimeError("Para exponer la cámara en LAN usa --cert-dir con HTTPS preparado")
    else:
        env.pop("LOCAL_TLS_CERT",None)
        env.pop("LOCAL_TLS_KEY",None)
    env["APP_ALLOWED_ORIGINS"]=",".join(f"{scheme}://{h}:{args.front_port}" for h in dict.fromkeys([host,"localhost","127.0.0.1"]))
    # load_settings lee .env sin mostrar su token. Restaurar el entorno del supervisor.
    previous=os.environ.copy()
    try:
        os.environ.update(env)
        settings=load_settings()
    finally:
        os.environ.clear()
        os.environ.update(previous)
    env["APP_TOKEN"]=settings.token
    if args.mode=="real" and not Path(settings.models.pose.model_path).is_file():
        raise RuntimeError("Falta el modelo Pose; ejecuta scripts/download_pose_model.py")
    if not (ROOT/"frontend"/"node_modules"/"vite"/"bin"/"vite.js").is_file():
        raise RuntimeError("Faltan dependencias frontend: ejecuta npm ci en frontend")
    node=shutil.which("node")
    if not node:
        raise RuntimeError("No se encuentra Node.js")
    url=f"{scheme}://{host}:{args.front_port}"
    try:
        port_free(host,args.front_port)
        port_free("127.0.0.1",args.back_port)
    except RuntimeError:
        try:
            request=Request(url+'/api/health',headers={'Authorization':'Bearer '+settings.token})
            with urlopen(request,timeout=2,context=tls_context) as response:health=json.load(response)
            if health.get('name')=='VisionPsy-Local' and health.get('pose')==env['POSE_BACKEND']:
                return env,settings,node,url,tls_context,True
        except (OSError,ValueError):pass
        raise
    return env,settings,node,url,tls_context,False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",choices=["real","demo"],default="real")
    parser.add_argument("--host",type=host_name,default="127.0.0.1")
    parser.add_argument("--front-port",type=int,choices=range(1024,65536),default=5175,metavar="PORT")
    parser.add_argument("--back-port",type=int,choices=range(1024,65536),default=8002,metavar="PORT")
    parser.add_argument("--cert-dir",type=Path)
    parser.add_argument("--database",type=Path)
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--open",action="store_true",help="Abrir el navegador al estar listo")
    parser.add_argument("--serve-ca",action="store_true",help="Publicar solo la CA para preparar el celular")
    parser.add_argument("--ca-port",type=int,choices=range(1024,65536),default=8765,metavar="PORT")
    parser.add_argument("--runtime-seconds",type=float,default=0,help="Detener después de N segundos; útil para ensayos automatizados")
    args=parser.parse_args()
    env,settings,node,url,context,existing=prepare(args)
    print(json.dumps({"url":url,"camera_url":url+"/#/phone","pose":env["POSE_BACKEND"],"notifications":settings.notifications.enabled,"checks":"ok"}),flush=True)
    if args.check:
        return
    if existing:
        print('VisionPsy ya está abierto. No se iniciarán procesos duplicados.',flush=True)
        if args.open:webbrowser.open(url)
        return
    children=[]
    logs=[]
    ca_server=None
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if args.serve_ca:
            if not args.cert_dir:raise RuntimeError('--serve-ca requiere --cert-dir')
            if args.ca_port in (args.front_port,args.back_port):raise RuntimeError('El puerto del certificado debe ser distinto')
            ca_server=public_certificate_server(args.host,args.ca_port,args.cert_dir,url)
        for name,command,cwd in [
            ("backend",[sys.executable,"-m","backend.main"],ROOT),
            ("frontend",[node,str(ROOT/"frontend/node_modules/vite/bin/vite.js"),"--host",args.host,"--port",str(args.front_port)],ROOT/"frontend")]:
            (ROOT/"reports").mkdir(exist_ok=True)
            log=(ROOT/"reports"/f"local-{name}.log").open("a",encoding="utf-8")
            logs.append(log)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0))
        ready=False
        request=Request(url+"/api/health",headers={"Authorization":f"Bearer {settings.token}"})
        deadline=time.monotonic()+max(45,settings.models.vision.startup_timeout_seconds+15)
        while time.monotonic()<deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Un servicio no pudo arrancar; revisa reports/local-backend.log y local-frontend.log")
            try:
                with urlopen(request,timeout=2,context=context) as response:
                    health=json.load(response)
                if health.get("pose")==env["POSE_BACKEND"]:
                    ready=True
                    break
            except (URLError,TimeoutError,OSError):
                time.sleep(.25)
        if not ready:
            raise RuntimeError("El proxy no confirmó la salud del backend dentro del plazo")
        print("Servicios listos. Ctrl+C para detener.",flush=True)
        print(f'VisionPsy: {url}',flush=True)
        if args.open:
            webbrowser.open(f'http://{args.host}:{args.ca_port}/' if args.serve_ca else url)
        started=time.monotonic()
        while not args.runtime_seconds or time.monotonic()-started<args.runtime_seconds:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Un servicio terminó; se detiene el conjunto para evitar un monitor incompleto")
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        if ca_server:
            ca_server.shutdown();ca_server.server_close()
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for log in logs:
            log.close()


if __name__=="__main__":
    try:
        main()
    except (RuntimeError,ValueError,OSError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
