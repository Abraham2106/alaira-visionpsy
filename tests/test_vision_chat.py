import base64
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.interfaces import VisionAnswer
from backend.visionpsy import VisionPsyBusyError


def test_chat_is_authenticated_stateless_and_does_not_create_alerts(settings,jpeg):
    calls=[]
    class Model:
        async def ask(self,image,question):
            calls.append((image,question))
            return VisionAnswer("STANDING")
    with TestClient(create_app(settings,vision=Model())) as client:
        body={"image":base64.b64encode(jpeg).decode(),"question":"What position?"}
        assert client.post('/vision/ask',json=body).status_code==401
        headers={"Authorization":"Bearer "+settings.token}
        response=client.post('/vision/ask',json=body,headers=headers)
        assert response.status_code==200 and response.json()['answer']=='STANDING'
        assert response.json()['seconds']>=0
        assert calls==[(jpeg,'What position?')]
        assert client.get('/alerts',headers=headers).json()==[]
        for invalid in ({'image':'not-base64','question':'Test'},{'image':'','question':'Test'},{'image':'a'*2700001,'question':'Test'},{'image':body['image'],'question':' '*4}):
            response=client.post('/vision/ask',json=invalid,headers=headers)
            assert response.status_code in (400,422)
            assert 'a'*100 not in response.text
        assert len(calls)==1


def test_chat_reports_busy_without_queueing_another_inference(settings,jpeg):
    class Model:
        async def ask(self,image,question):
            raise VisionPsyBusyError('busy')
    with TestClient(create_app(settings,vision=Model())) as client:
        response=client.post('/vision/ask',headers={"Authorization":"Bearer "+settings.token},json={"image":base64.b64encode(jpeg).decode(),"question":"Test"})
        assert response.status_code==409
