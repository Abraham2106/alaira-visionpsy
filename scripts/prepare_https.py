"""Genera CA y certificado local con OpenSSL, sin modificar almacenes de confianza."""
import argparse
import ipaddress
import json
import re
import shutil
import ssl
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def host_name(value):
    try:
        address = ipaddress.ip_address(value)
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError("Usa una dirección local concreta")
        return str(address)
    except ValueError:
        if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
            raise argparse.ArgumentTypeError("Nombre/IP local inválido")
        # Las IP con formato válido pero públicas no deben entrar como DNS.
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return value.lower()
        raise argparse.ArgumentTypeError("Usa una dirección privada o loopback concreta")


def prepare(host, output, openssl=None):
    host = host_name(host)
    output = Path(output).resolve()
    tool = openssl or shutil.which("openssl")
    if not tool:
        raise RuntimeError("OpenSSL no está disponible; instala una distribución oficial o usa mkcert según la guía HTTPS")
    output.mkdir(parents=True, exist_ok=True)
    names = {name:output / name for name in ["ca.pem","ca-key.pem","server.pem","server-key.pem","server.csr","server.ext"]}
    if any(names[n].exists() for n in ["ca.pem","ca-key.pem","server.pem","server-key.pem"]):
        raise RuntimeError("El directorio ya contiene certificados; usa otro directorio para evitar reemplazar claves")

    def run(*args):
        result = subprocess.run([tool,*map(str,args)],capture_output=True,text=True,timeout=30)
        if result.returncode:
            raise RuntimeError("OpenSSL no pudo preparar el certificado local. No se modificó la confianza del sistema.")

    run("req","-x509","-newkey","rsa:2048","-nodes","-sha256","-days","365",
        "-keyout",names["ca-key.pem"],"-out",names["ca.pem"],"-subj","/CN=Alaira VisionPsy Local CA",
        "-addext","basicConstraints=critical,CA:TRUE","-addext","keyUsage=critical,keyCertSign,cRLSign")
    run("req","-new","-newkey","rsa:2048","-nodes","-keyout",names["server-key.pem"],
        "-out",names["server.csr"],"-subj",f"/CN={host}")
    alt = ["DNS:localhost","IP:127.0.0.1"]
    try:
        ipaddress.ip_address(host)
        alt.append(f"IP:{host}")
    except ValueError:
        alt.append(f"DNS:{host}")
    names["server.ext"].write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName="+",".join(dict.fromkeys(alt))+"\n",encoding="ascii")
    run("x509","-req","-in",names["server.csr"],"-CA",names["ca.pem"],"-CAkey",names["ca-key.pem"],
        "-CAcreateserial","-out",names["server.pem"],"-days","30","-sha256","-extfile",names["server.ext"])
    for key in [names["ca-key.pem"],names["server-key.pem"]]:
        key.chmod(0o600)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(names["server.pem"],names["server-key.pem"])
    result={"host":host,"certificate":str(names["server.pem"]),"key":str(names["server-key.pem"]),
            "public_ca":str(names["ca.pem"]),"trust_installed":False,"valid_days":30}
    (output/"https.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host",type=host_name,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"certs"/"local")
    args=parser.parse_args()
    result=prepare(args.host,args.output)
    print(json.dumps(result,indent=2))
    print("Confianza no instalada. Solo ca.pem es distribuible; conserva las dos claves privadas en la PC.")


if __name__ == "__main__":
    main()
