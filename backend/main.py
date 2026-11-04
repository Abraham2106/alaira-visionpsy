# Aplicación FastAPI local con REST autenticado y adaptadores WebSocket de ingesta y dashboard.
import asyncio
import secrets
import os
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, Request, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .alert_lifecycle import IllegalTransition
from .config import Settings, load_settings
from .model_loader import ModelLoadError, load_pose_estimator, load_vision_model
from .pipeline import Pipeline
from .domain import EventAction, Zone, ZonesDocument
from .storage import Repository, RevisionConflict
from .notifications import NotificationWorker
from .ws_handler import ConnectionManager, authenticate, handle_dashboard, handle_ingest


def create_app(settings: Settings | None = None, *, estimator=None, vision=None, clock=time.time) -> FastAPI:
    settings = settings or load_settings()
    security = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = settings
        app.state.settings = current
        if current.notifications.enabled and not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
            raise RuntimeError("notifications.enabled requiere TELEGRAM_BOT_TOKEN en el entorno local")
        async with AsyncExitStack() as resources:
            try:
                pose_model = estimator if estimator is not None else load_pose_estimator(current)
                close_estimator = getattr(pose_model, "close", None)
                if close_estimator is not None:
                    resources.push_async_callback(asyncio.to_thread, close_estimator)
                vision_model = vision if vision is not None else load_vision_model(current)
            except (ModelLoadError, NotImplementedError) as error:
                raise RuntimeError(f"No se pudo iniciar VisionPsy-Local: {error}") from error
            repository = Repository(current.storage.path)
            resources.callback(repository.close)
            document = repository.zones()
            if document.revision == 0 and current.risk.safe_zones:
                document = repository.replace_zones(ZonesDocument(zones=[
                    Zone(id=f"zone-{i}", name=f"Zona {i+1}", polygon=p) for i,p in enumerate(current.risk.safe_zones)]))
            if document.revision:
                current = current.model_copy(update={"risk":current.risk.model_copy(update={"safe_zones":[z.polygon for z in document.zones]})})
                app.state.settings = current
            manager = ConnectionManager(current.server.send_timeout_seconds)
            pipeline = Pipeline(current, pose_model, vision_model, manager, clock, repository=repository)
            app.state.manager, app.state.pipeline = manager, pipeline
            app.state.repository = repository
            worker = NotificationWorker(repository, pipeline, current.notifications, clock=clock)
            app.state.notifier = worker
            notification_task = None
            if current.notifications.enabled:
                notification_task = asyncio.create_task(worker.run())

            async def ticker():
                maintenance_at = clock()
                while True:
                    await asyncio.sleep(current.server.tick_seconds)
                    await pipeline.tick()
                    if clock() - maintenance_at >= 60:
                        await pipeline.alerts.prune(clock(), current.storage.retention_days)
                        await pipeline.technical.prune(clock(), current.storage.retention_days)
                        maintenance_at = clock()

            task = asyncio.create_task(ticker())
            try:
                yield
            finally:
                task.cancel()
                if notification_task:
                    notification_task.cancel()
                    await asyncio.gather(notification_task, return_exceptions=True)
                await asyncio.gather(task, return_exceptions=True)
                await pipeline.close()

    app = FastAPI(title="VisionPsy-Local", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    async def require_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        expected = app.state.settings.token
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Token requerido o inválido",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health", dependencies=[Depends(require_token)])
    async def health():
        current = app.state.settings
        return {"status": "ok", "name": "VisionPsy-Local", "pose": current.models.pose.backend,
                "vision": current.models.vision.backend, "scenario": current.models.pose.scenario,
                "synthetic": current.models.pose.backend == "stub"}

    @app.get("/alerts", dependencies=[Depends(require_token)])
    async def alerts(limit: int = Query(default=50,ge=1,le=200)):
        return await asyncio.to_thread(app.state.repository.alerts,limit)

    @app.get("/zones", dependencies=[Depends(require_token)])
    async def zones():
        return app.state.repository.zones()

    @app.put("/zones", dependencies=[Depends(require_token)])
    async def replace_zones(document: ZonesDocument):
        pipeline = app.state.pipeline
        async with pipeline._lock:
            try:
                updated = await asyncio.to_thread(app.state.repository.replace_zones, document)
            except RevisionConflict as error:
                raise HTTPException(409, str(error)) from error
            pipeline.settings = pipeline.settings.model_copy(update={"risk":pipeline.settings.risk.model_copy(
                update={"safe_zones":[z.polygon for z in updated.zones]})})
            pipeline.history.clear()
            await pipeline.alerts.observe(None, clock())
            return updated

    @app.post("/alerts/{alert_id}/action", dependencies=[Depends(require_token)])
    async def event_action(alert_id: str, body: EventAction):
        try:
            return await app.state.pipeline.act(alert_id, body.action, body.reason, clock())
        except KeyError as error:
            raise HTTPException(404,"Evento no encontrado") from error
        except IllegalTransition as error:
            raise HTTPException(409,str(error)) from error

    @app.get("/alerts/{alert_id}/actions", dependencies=[Depends(require_token)])
    async def actions(alert_id: str):
        return app.state.repository.event_actions(alert_id)

    @app.get("/notifications", dependencies=[Depends(require_token)])
    async def notifications():
        return {"enabled":app.state.settings.notifications.enabled,"error":app.state.notifier.last_error,
                "deliveries":app.state.repository.deliveries()}

    @app.get("/contacts", dependencies=[Depends(require_token)])
    async def contacts():
        return app.state.repository.contacts()

    @app.delete("/contacts/{chat_id}", dependencies=[Depends(require_token)])
    async def remove_contact(chat_id: str):
        app.state.repository.revoke_contact(chat_id)
        return {"ok":True}

    @app.post("/pairing/{purpose}", dependencies=[Depends(require_token)])
    async def pairing(purpose: str):
        if purpose not in {"camera","telegram","telegram_backup"}:
            raise HTTPException(404,"Tipo de vinculación desconocido")
        return app.state.repository.issue_code(purpose,clock())

    attempts = defaultdict(deque)
    class CameraPair(BaseModel):
        code: str = Field(min_length=8, max_length=100)

    @app.post("/camera/pair")
    async def camera_pair(body: CameraPair, request: Request):
        address = request.client.host if request.client else "local"
        now = time.monotonic()
        if len(attempts) > 1024:
            for key in list(attempts):
                if not attempts[key] or now-attempts[key][-1] > 60:
                    del attempts[key]
        if address not in attempts and len(attempts) >= 1024:
            raise HTTPException(429,"Demasiadas solicitudes")
        bucket=attempts[address]
        while bucket and now-bucket[0]>60:
            bucket.popleft()
        if len(bucket)>=5:
            raise HTTPException(429,"Espera un minuto antes de reintentar")
        bucket.append(now)
        if not app.state.repository.consume_code(body.code,"camera",clock()):
            raise HTTPException(403,"Código inválido o vencido")
        return {"token":app.state.repository.camera_credential(clock())}

    @app.delete("/camera/pair", dependencies=[Depends(require_token)])
    async def revoke_camera():
        app.state.repository.revoke_camera()
        if app.state.manager.producer:
            await app.state.manager.producer.close(code=1008,reason="Cámara desvinculada")
        return {"ok":True}

    @app.post("/alerts/{alert_id}/ack", dependencies=[Depends(require_token)])
    async def acknowledge(alert_id: str):
        try:
            alert = await app.state.pipeline.alerts.acknowledge(alert_id, clock())
            return alert.model_dump(mode="json")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Alerta no encontrada") from error
        except IllegalTransition as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.websocket("/ws/dashboard")
    async def dashboard(ws: WebSocket):
        if await authenticate(ws, app.state.settings):
            await handle_dashboard(ws, app.state.manager, app.state.pipeline)

    @app.websocket("/ws/ingest")
    async def ingest(ws: WebSocket):
        if await authenticate(ws, app.state.settings, app.state.repository.camera_authorized):
            await handle_ingest(ws, app.state.manager, app.state.pipeline)

    app.add_middleware(CORSMiddleware, allow_origins=settings.server.allowed_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])
    return app


def configured_app() -> FastAPI:
    return create_app(load_settings())


if __name__ == "__main__":
    import uvicorn
    current = load_settings()
    uvicorn.run(create_app(current), host=current.server.host, port=current.server.port,
                ws_max_size=current.server.max_frame_bytes)
