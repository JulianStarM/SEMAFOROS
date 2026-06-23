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
    title="Sistema Inteligente de Gestión de Semáforos",
    description="""
## 🚦 Sistema Inteligente de Control Semafórico

Plataforma para gestión y control automático de semáforos en tiempo real.

### Características
- ✅ Obtención automática de mapas desde API externa
- ✅ Generación automática de semáforos por intersección
- ✅ Control manual y automático
- ✅ Ciclos automáticos con WebSockets
- ✅ Dashboard en tiempo real
- ✅ Persistencia en Supabase/PostgreSQL

### Flujo
`API Mapas → Intersecciones → Semáforos → Dashboard → WebSocket`
    """,
    version="1.0.0",
    contact={"name": "Sistema Semáforos", "email": "admin@semaforos.local"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Mapas", "description": "Obtención de mapas desde API externa"},
        {"name": "Semáforos", "description": "CRUD y control de semáforos"},
        {"name": "Ciclos", "description": "Control del ciclo automático"},
        {"name": "Dashboard", "description": "Vista consolidada del sistema"},
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
