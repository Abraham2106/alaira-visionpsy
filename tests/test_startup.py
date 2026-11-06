"""Setup must be repeatable and must never expose credentials or private certificates."""
import hashlib
from io import BytesIO
import json
import ssl
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from dotenv import dotenv_values
from scripts.setup_local import ensure_token
from scripts import download_pose_model
from scripts.prepare_https import prepare
from scripts.run_local import public_certificate_server
from scripts import run_local


def test_token_is_generated_once_and_existing_settings_are_preserved(tmp_path,monkeypatch):
    monkeypatch.delenv('APP_TOKEN',raising=False)
    (tmp_path/'backend').mkdir()
    ensure_token(tmp_path)
    path=tmp_path/'backend/.env'
    first=path.read_bytes()
    token=dotenv_values(path)['APP_TOKEN']
    assert len(token)>=40
    ensure_token(tmp_path)
    assert path.read_bytes()==first
    monkeypatch.delenv('APP_TOKEN',raising=False)
    path.write_text('APP_TOKEN=existing-private-token\nTELEGRAM_BOT_TOKEN=keep-me\n')
    previous=path.read_bytes()
    ensure_token(tmp_path)
    assert path.read_bytes()==previous


def test_existing_session_is_opened_without_spawning_duplicate_processes(settings,monkeypatch):
    opened=[]
    monkeypatch.setattr('sys.argv',['run_local.py','--open'])
    monkeypatch.setattr(run_local,'prepare',lambda args:({'POSE_BACKEND':'mediapipe'},settings,'node','http://127.0.0.1:5175',None,True))
    monkeypatch.setattr(run_local.webbrowser,'open',opened.append)
    monkeypatch.setattr(run_local.subprocess,'Popen',lambda *a,**k:pytest.fail('Duplicate services'))
    run_local.main()
    assert opened==['http://127.0.0.1:5175']


def test_verified_model_is_not_downloaded_again(tmp_path,monkeypatch):
    model=tmp_path/'pose.task';model.write_bytes(b'verified-model')
    monkeypatch.setattr(download_pose_model,'MODEL_PATH',model)
    monkeypatch.setattr(download_pose_model,'MODEL_SHA256',hashlib.sha256(model.read_bytes()).hexdigest())
    monkeypatch.setattr(download_pose_model,'urlopen',lambda *a,**k:pytest.fail('Unnecessary download'))
    download_pose_model.main()


def test_corrupt_download_does_not_replace_existing_model(tmp_path,monkeypatch):
    model=tmp_path/'pose.task';model.write_bytes(b'keep-existing')
    monkeypatch.setattr(download_pose_model,'MODEL_PATH',model)
    monkeypatch.setattr(download_pose_model,'MODEL_SHA256',hashlib.sha256(b'correct').hexdigest())
    class Download(BytesIO):
        def geturl(self):return 'https://storage.googleapis.com/model'
    monkeypatch.setattr(download_pose_model,'urlopen',lambda *a,**k:Download(b'bad-download'))
    with pytest.raises(RuntimeError,match='SHA-256'):download_pose_model.main()
    assert model.read_bytes()==b'keep-existing'
    assert not model.with_suffix('.task.part').exists()


def test_certificates_work_without_openssl_and_http_exposes_only_public_ca(tmp_path,monkeypatch):
    pytest.importorskip('cryptography')
    monkeypatch.setattr('scripts.prepare_https.shutil.which',lambda name:None)
    folder=tmp_path/'certs'
    result=prepare('127.0.0.1',folder)
    assert result['trust_installed'] is False
    assert json.loads((folder/'https.json').read_text())['host']=='127.0.0.1'
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(result['certificate'],result['key'])
    ssl.create_default_context(cafile=result['public_ca'])
    server=public_certificate_server('127.0.0.1',0,folder,'https://127.0.0.1:5175')
    base=f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urlopen(base+'/ca.crt') as response:assert response.read()==(folder/'ca.pem').read_bytes()
        with urlopen(base+'/') as response:assert b'https://127.0.0.1:5175' in response.read()
        for path in ('/ca-key.pem','/server-key.pem','/../ca-key.pem'):
            with pytest.raises(HTTPError) as error:urlopen(base+path)
            assert error.value.code==404
    finally:server.shutdown();server.server_close()
