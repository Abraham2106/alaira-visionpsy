"""Genera CA y certificado local con OpenSSL, sin modificar almacenes de confianza."""
import argparse
import ipaddress
import json
import re
import shutil
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
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
    output.mkdir(parents=True, exist_ok=True)
    names = {name:output / name for name in ["ca.pem","ca-key.pem","server.pem","server-key.pem","server.csr","server.ext"]}
    if any(names[n].exists() for n in ["ca.pem","ca-key.pem","server.pem","server-key.pem"]):
        raise RuntimeError("El directorio ya contiene certificados; usa otro directorio para evitar reemplazar claves")

    if not tool:
        return prepare_with_python(host, output, names)

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


def prepare_with_python(host, output, names):
    """Same certificate contract on a fresh Windows PC without an OpenSSL CLI."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now=datetime.now(timezone.utc)
    ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    issuer=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Alaira VisionPsy Local CA')])
    ca=(x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
        .sign(ca_key,hashes.SHA256()))
    alt=[x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
    try: item=x509.IPAddress(ipaddress.ip_address(host))
    except ValueError: item=x509.DNSName(host)
    if item not in alt:alt.append(item)
    cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host)]))
        .issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectAlternativeName(alt),critical=False)
        .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        .sign(ca_key,hashes.SHA256()))
    for name,material in [('ca-key.pem',ca_key),('server-key.pem',key)]:
        with names[name].open('xb') as file:
            names[name].chmod(0o600)
            file.write(material.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    names['ca.pem'].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    names['server.pem'].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(names['server.pem'],names['server-key.pem'])
    result={'host':host,'certificate':str(names['server.pem']),'key':str(names['server-key.pem']),
            'public_ca':str(names['ca.pem']),'trust_installed':False,'valid_days':30}
    (output/'https.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
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
