"""Idempotent local setup used by run.cmd; never prints credentials or opens a camera."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values, set_key
from scripts.download_pose_model import main as download_pose
from scripts.prepare_https import host_name, prepare


def ensure_token(root=ROOT):
    path=root/'backend'/'.env'
    current=dotenv_values(path) if path.exists() else {}
    token=os.environ.get('APP_TOKEN','').strip() or (current.get('APP_TOKEN') or '').strip()
    if not token:
        token=secrets.token_urlsafe(32)
        path.touch(mode=0o600,exist_ok=True)
        set_key(str(path),'APP_TOKEN',token)
    os.environ['APP_TOKEN']=token


def local_address():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as connection:
        # UDP connect selects a local interface; it sends no packet.
        connection.connect(('192.0.2.1',9))
        address=connection.getsockname()[0]
    return host_name(address)


def certificate_for(host):
    from cryptography import x509
    prefix='local-'+host.replace(':','-')
    parent=ROOT/'certs'
    for folder in sorted(parent.glob('*'),reverse=True):
        try:
            metadata=json.loads((folder/'https.json').read_text(encoding='utf-8'))
            cert=x509.load_pem_x509_certificate((folder/'server.pem').read_bytes())
            if metadata['host']==host and cert.not_valid_after_utc>datetime.now(timezone.utc):
                return folder
        except (OSError,ValueError,KeyError):
            continue
    folder=parent/(prefix+'-'+secrets.token_hex(3))
    prepare(host,folder)
    return folder


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phone',action='store_true')
    parser.add_argument('--host',type=host_name)
    parser.add_argument('--front-port',type=int,default=5175)
    parser.add_argument('--back-port',type=int,default=8002)
    parser.add_argument('--ca-port',type=int,default=8765)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--runtime-seconds',type=float,default=0)
    args=parser.parse_args()
    ensure_token()
    download_pose()
    host=args.host or (local_address() if args.phone else '127.0.0.1')
    command=[sys.executable,str(ROOT/'scripts/run_local.py'),'--mode','real','--host',host,
             '--front-port',str(args.front_port),'--back-port',str(args.back_port)]
    if args.phone:
        folder=certificate_for(host)
        print(f'Celular: http://{host}:{args.ca_port}/ca.crt',flush=True)
        print('Primera vez: instala SOLO ese certificado publico en la PC y el celular. No se cambia la confianza automaticamente.',flush=True)
        command+=['--cert-dir',str(folder),'--serve-ca','--ca-port',str(args.ca_port)]
    if args.check:command+=['--check']
    elif not args.no_browser:command+=['--open']
    if args.runtime_seconds:command+=['--runtime-seconds',str(args.runtime_seconds)]
    return subprocess.call(command,cwd=ROOT)


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,RuntimeError,ValueError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
