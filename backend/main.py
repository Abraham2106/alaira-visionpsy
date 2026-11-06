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

from .alert_lifecycle import AlertStore, IllegalTransition
from .consolidator import RoomConsolidator
from .config import Settings, load_settings
from .model_loader import ModelLoadError, load_pose_estimator, load_vision_model
from .pipeline import Pipeline
from .domain import EventAction, Zone, ZonesDocument
from .storage import DEFAULT_CAMERA, Repository, RevisionConflict
from .notifications import NotificationWorker
from .ws_handler import ConnectionManager, authenticate, handle_dashboard, handle_ingest


def create_app(settings: Settings | None = None, *, estimator=None, vision=None, clock=time.time,
               estimator_factory=None) -> FastAPI:
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
                close_vision = getattr(vision_model, "aclose", None)
                if close_vision is not None:
                    resources.push_async_callback(close_vision)
                start_vision = getattr(vision_model, "start", None)
                if start_vision is not None:
                    await start_vision()
            except (ModelLoadError, NotImplementedError) as error:
                raise RuntimeError(f"No se pudo iniciar VisionPsy-Local: {error}") from error
            repository = Repository(current.storage.path)
            resources.callback(repository.close)
            await asyncio.to_thread(repository.prune, clock(), current.storage.retention_days)
            manager = ConnectionManager(current.server.send_timeout_seconds)
            room = RoomConsolidator(AlertStore(current.alerts, manager, repository=repository),
                                    stale_seconds=current.risk.max_pose_gap_seconds)
            pipelines: dict[str, Pipeline] = {}
            estimators: dict[str, object] = {}
            seed = repository.zones(DEFAULT_CAMERA)
            if seed.revision == 0 and current.risk.safe_zones:
                repository.replace_zones(ZonesDocument(zones=[
                    Zone(id=f"zone-{i}", name=f"Zona {i+1}", polygon=p) for i,p in enumerate(current.risk.safe_zones)]), DEFAULT_CAMERA)

            def build_pipeline(camera_id: str, model) -> Pipeline:
                document = repository.zones(camera_id)
                camera_settings = current
                if document.revision:
                    camera_settings = current.model_copy(update={"risk":current.risk.model_copy(
                        update={"safe_zones":[z.polygon for z in document.zones]})})
                estimators[camera_id] = model
                pipelines[camera_id] = Pipeline(camera_settings, model, vision_model, manager, clock,
                                                repository=repository, camera_id=camera_id, room=room)
                return pipelines[camera_id]

            def new_estimator():
                return estimator_factory() if estimator_factory is not None else load_pose_estimator(current)

            for index, camera in enumerate(repository.cameras()):
                model = pose_model if index == 0 else new_estimator()
                build_pipeline(camera["id"], model)
            if DEFAULT_CAMERA not in pipelines:
                raise RuntimeError("Falta la cámara principal cam-1")
            app.state.settings = current
            app.state.manager, app.state.pipelines, app.state.room = manager, pipelines, room
            app.state.pipeline = pipelines[DEFAULT_CAMERA]
            app.state.repository = repository
            app.state.build_pipeline, app.state.new_estimator, app.state.estimators = build_pipeline, new_estimator, estimators
            worker = NotificationWorker(repository, room, current.notifications, clock=clock)
            app.state.notifier = worker
            notification_task = None
            if current.notifications.enabled:
                notification_task = asyncio.create_task(worker.run())

            async def ticker():
                maintenance_at = clock()
                while True:
                    await asyncio.sleep(current.server.tick_seconds)
                    for pipeline in tuple(pipelines.values()):
                        await pipeline.tick()
                    if clock() - maintenance_at >= 60:
                        await room.alerts.prune(clock(), current.storage.retention_days)
                        for pipeline in tuple(pipelines.values()):
                            await pipeline.technical.prune(clock(), current.storage.retention_days)
                        maintenance_at = clock()

            async def close_extra_estimators():
                # cam-1 la cierra el AsyncExitStack; las demás se crean y se retiran en caliente.
                for camera_id, model in tuple(estimators.items()):
                    close = getattr(model, "close", None)
                    if camera_id != DEFAULT_CAMERA and close is not None:
                        await asyncio.to_thread(close)
            resources.push_async_callback(close_extra_estimators)

            task = asyncio.create_task(ticker())
            try:
                yield
            finally:
                task.cancel()
                if notification_task:
                    notification_task.cancel()
                    await asyncio.gather(notification_task, return_exceptions=True)
                await asyncio.gather(task, return_exceptions=True)
                for pipeline in tuple(pipelines.values()):
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

    def known_pipeline(camera_id: str) -> Pipeline:
        pipeline = app.state.pipelines.get(camera_id)
        if pipeline is None:
            raise HTTPException(404, "Cámara no encontrada")
        return pipeline

    @app.get("/zones", dependencies=[Depends(require_token)])
    async def zones(camera_id: str = Query(default=DEFAULT_CAMERA)):
        known_pipeline(camera_id)
        return app.state.repository.zones(camera_id)

    @app.put("/zones", dependencies=[Depends(require_token)])
    async def replace_zones(document: ZonesDocument, camera_id: str = Query(default=DEFAULT_CAMERA)):
        pipeline = known_pipeline(camera_id)
        async with pipeline._lock:
            try:
                updated = await asyncio.to_thread(app.state.repository.replace_zones, document, camera_id)
            except RevisionConflict as error:
                raise HTTPException(409, str(error)) from error
            pipeline.settings = pipeline.settings.model_copy(update={"risk":pipeline.settings.risk.model_copy(
                update={"safe_zones":[z.polygon for z in updated.zones]})})
            pipeline.history.clear()
            await pipeline._observe(None, clock())
            return updated

    def camera_view(row):
        pipeline = app.state.pipelines.get(row["id"])
        return {"id":row["id"],"name":row["name"],
                "state":pipeline.last_status.camera if pipeline else "waiting",
                "connected":row["id"] in app.state.manager.producers}

    class CameraCreate(BaseModel):
        name: str = Field(min_length=1, max_length=80)
        id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,32}$")

    class CameraRename(BaseModel):
        name: str = Field(min_length=1, max_length=80)

    @app.get("/cameras", dependencies=[Depends(require_token)])
    async def cameras():
        return [camera_view(row) for row in app.state.repository.cameras()]

    @app.post("/cameras", dependencies=[Depends(require_token)], status_code=201)
    async def create_camera(body: CameraCreate):
        repository = app.state.repository
        existing = {row["id"] for row in repository.cameras()}
        if len(existing) >= app.state.settings.cameras.max:
            raise HTTPException(409, f"Máximo de {app.state.settings.cameras.max} cámaras")
        camera_id = body.id or next(f"cam-{n}" for n in range(1, 100) if f"cam-{n}" not in existing)
        try:
            row = repository.add_camera(camera_id, body.name, clock())
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        model = await asyncio.to_thread(app.state.new_estimator)
        app.state.build_pipeline(camera_id, model)
        return camera_view(row)

    @app.patch("/cameras/{camera_id}", dependencies=[Depends(require_token)])
    async def rename_camera(camera_id: str, body: CameraRename):
        try:
            return camera_view(app.state.repository.rename_camera(camera_id, body.name))
        except (KeyError, ValueError) as error:
            raise HTTPException(404, "Cámara no encontrada") from error

    @app.delete("/cameras/{camera_id}", dependencies=[Depends(require_token)])
    async def delete_camera(camera_id: str):
        try:
            app.state.repository.remove_camera(camera_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, "Cámara no encontrada") from error
        producer = app.state.manager.producers.get(camera_id)
        if producer:
            await producer.close(code=1008, reason="Cámara eliminada")
        pipeline = app.state.pipelines.pop(camera_id, None)
        model = app.state.estimators.pop(camera_id, None)
        app.state.room.pipelines.pop(camera_id, None)
        app.state.room.latest.pop(camera_id, None)
        if pipeline:
            await pipeline.close()
        close = getattr(model, "close", None)
        if close is not None:
            await asyncio.to_thread(close)
        return {"ok":True}

    @app.post("/alerts/{alert_id}/action", dependencies=[Depends(require_token)])
    async def event_action(alert_id: str, body: EventAction):
        try:
            return await app.state.room.act(alert_id, body.action, body.reason, clock())
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

    def camera_purpose(camera_id: str) -> str:
        return "camera" if camera_id == DEFAULT_CAMERA else f"camera:{camera_id}"

    @app.post("/pairing/{purpose}", dependencies=[Depends(require_token)])
    async def pairing(purpose: str, camera_id: str = Query(default=DEFAULT_CAMERA)):
        if purpose not in {"camera","telegram","telegram_backup"}:
            raise HTTPException(404,"Tipo de vinculación desconocido")
        if purpose == "camera":
            known_pipeline(camera_id)
            purpose = camera_purpose(camera_id)
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
        repository = app.state.repository
        # El código identifica a qué cámara se vincula el teléfono; la credencial lo hereda.
        camera_id = next((row["id"] for row in repository.cameras()
                          if repository.consume_code(body.code, camera_purpose(row["id"]), clock())), None)
        if camera_id is None:
            raise HTTPException(403,"Código inválido o vencido")
        return {"token":repository.camera_credential(clock(), camera_id),"camera_id":camera_id}

    @app.delete("/camera/pair", dependencies=[Depends(require_token)])
    async def revoke_camera(camera_id: str | None = Query(default=None)):
        if camera_id is not None:
            known_pipeline(camera_id)
        app.state.repository.revoke_camera(camera_id)
        targets = list(app.state.manager.producers) if camera_id is None else [camera_id]
        for target in targets:
            producer = app.state.manager.producers.get(target)
            if producer:
                await producer.close(code=1008,reason="Cámara desvinculada")
        return {"ok":True}

    @app.post("/alerts/{alert_id}/ack", dependencies=[Depends(require_token)])
    async def acknowledge(alert_id: str):
        try:
            alert = await app.state.room.acknowledge(alert_id, clock())
            return alert.model_dump(mode="json")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Alerta no encontrada") from error
        except IllegalTransition as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.websocket("/ws/dashboard")
    async def dashboard(ws: WebSocket):
        if await authenticate(ws, app.state.settings):
            await handle_dashboard(ws, app.state.manager, app.state.pipelines)

    @app.websocket("/ws/ingest")
    async def ingest(ws: WebSocket):
        if await authenticate(ws, app.state.settings, app.state.repository.camera_authorized):
            await handle_ingest(ws, app.state.manager, app.state.pipelines)

    app.add_middleware(CORSMiddleware, allow_origins=settings.server.allowed_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])
    return app


def configured_app() -> FastAPI:
    return create_app(load_settings())


if __name__ == "__main__":
    import uvicorn
    current = load_settings()
    uvicorn.run(create_app(current), host=current.server.host, port=current.server.port,
                ws_max_size=current.server.max_frame_bytes)
