"""HTTPS real en loopback: CA explícita, hostname y rechazo de confianza ausente."""
import argparse
import shutil
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from scripts.prepare_https import host_name, prepare
from scripts.run_local import port_free


@pytest.mark.parametrize("host",["0.0.0.0","8.8.8.8","a\nsubjectAltName=bad","-bad","127.0.0.1/evil"])
def test_invalid_certificate_hosts_are_rejected(host):
    with pytest.raises(argparse.ArgumentTypeError):
        host_name(host)


def test_port_conflict_is_explicit():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        sock.listen()
        with pytest.raises(RuntimeError,match="puerto ocupado"):
            port_free("127.0.0.1",sock.getsockname()[1])


@pytest.mark.skipif(not shutil.which("openssl"),reason="La generación HTTPS requiere OpenSSL local")
def test_https_trust_and_hostname_are_verified_without_installing_ca(tmp_path):
    result=prepare("127.0.0.1",tmp_path/"certs")
    assert result["trust_installed"] is False
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"local-https-ok")
        def log_message(self,*_):
            pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(result["certificate"],result["key"])
    server.socket=server_context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        url=f"https://127.0.0.1:{server.server_address[1]}"
        trusted=ssl.create_default_context(cafile=result["public_ca"])
        with urlopen(url,context=trusted,timeout=3) as response:
            assert response.read()==b"local-https-ok"
        with pytest.raises(URLError):
            urlopen(url,context=ssl.create_default_context(),timeout=3)
        with socket.create_connection(server.server_address,timeout=3) as sock:
            with pytest.raises(ssl.SSLCertVerificationError):
                trusted.wrap_socket(sock,server_hostname="not-this-host.invalid")
        with pytest.raises(RuntimeError,match="ya contiene certificados"):
            prepare("127.0.0.1",tmp_path/"certs")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
