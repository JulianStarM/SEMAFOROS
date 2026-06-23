import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.routers.api import router
from app.websocket.manager import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚦 Sistema Inteligente de Semáforos iniciando...")
    yield
    logger.info("🛑 Sistema detenido.")


app = FastAPI(
    title="API de Gestión de Semáforos",
    summary="Servicio especializado para el control y monitoreo de semáforos en tiempo real.",
    description="""
## 🚦 API de Gestión de Semáforos

Servicio REST especializado en la gestión, monitoreo y control de semáforos dentro de una arquitectura distribuida de tráfico inteligente.

### Responsabilidad
Esta API se encarga **exclusivamente** de los semáforos:
- Consultar su estado actual (verde, amarillo, rojo).
- Conocer el tiempo restante hasta el próximo cambio.
- Configurar tiempos de funcionamiento.
- Activar/desactivar semáforos.
- Iniciar/detener ciclos automáticos.
- Obtener estadísticas y monitoreo en tiempo real.

### Integración con otros módulos
- **API de Mapas** → responsabilidad de otro módulo.
- **API de Vehículos** → responsabilidad de otro módulo.
- **API de Semáforos** → esta API.

### Caso de uso principal para sistemas externos
Un sistema externo puede consumir esta API para:
1. Obtener todos los semáforos existentes (`GET /api/semaforos`).
2. Conocer el estado actual de cada uno (`GET /api/semaforos/{id}/estado`).
3. Saber cuánto tiempo falta para el siguiente cambio (`GET /api/semaforos/{id}/tiempo`).
4. Consultar si el sistema está en modo automático o manual (`GET /api/ciclos/estado`).
5. Obtener estadísticas generales (`GET /api/estadisticas`).
6. Mostrar automáticamente los semáforos en su propio sistema.
    """,
    version="1.0.0",
    contact={"name": "Equipo de Tráfico Inteligente", "email": "api@semaforos.local"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Semáforos", "description": "Gestión completa de semáforos: estados, tiempos, activación y configuración."},
        {"name": "Ciclos", "description": "Control del ciclo automático de semáforos."},
        {"name": "Sistema", "description": "Estadísticas, dashboard y monitoreo del sistema."},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas API
app.include_router(router)

# Archivos estáticos
import os
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# WebSocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        from app.services.semaforo import obtener_dashboard
        try:
            dashboard = await obtener_dashboard()
            await manager.send_personal(websocket, {
                "tipo": "estado_inicial",
                "data": dashboard
            })
        except Exception as e:
            logger.warning(f"Error enviando estado inicial WS: {e}")

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"tipo": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Página principal
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page():
    with open("templates/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "servicio": "Sistema Inteligente de Semáforos"}
