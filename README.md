# 🚦 Sistema Inteligente de Gestión de Semáforos

Plataforma de control semafórico en tiempo real con FastAPI, Supabase y WebSockets.

## Arquitectura

```
API Externa (Mapas) ──► FastAPI Backend ──► Supabase/PostgreSQL
                              │
                         WebSockets
                              │
                       Dashboard HTML/JS
```

## Estructura del Proyecto

```
semaforos/
├── main.py                    # FastAPI app principal + WebSocket
├── requirements.txt
├── .env                       # Variables de entorno
├── supabase_init.sql          # Script SQL para crear tablas
├── app/
│   ├── database.py            # Cliente Supabase + fetch mapas
│   ├── models.py              # Modelos Pydantic
│   ├── routers/
│   │   └── api.py             # Todos los endpoints REST
│   ├── services/
│   │   └── semaforos.py       # Lógica de negocio + ciclo automático
│   └── websocket/
│       └── manager.py         # Gestor de conexiones WebSocket
├── templates/
│   └── index.html             # Dashboard SPA
└── static/                    # Assets estáticos
```

## Setup

### 1. Crear tablas en Supabase

Ir a: https://kfuddhujgzawigqgmxpd.supabase.co
→ SQL Editor → Nuevo query → Pegar contenido de `supabase_init.sql` → Run

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Ejecutar el servidor

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Abrir en navegador

- **Dashboard**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/mapas` | Obtener mapas desde API externa |
| POST | `/api/semaforos/generar` | Generar semáforos automáticamente |
| GET | `/api/semaforos` | Listar todos los semáforos |
| GET | `/api/semaforos/{id}` | Obtener semáforo por ID |
| GET | `/api/semaforos/mapa/{clave}` | Semáforos de un mapa |
| PUT | `/api/semaforos/{id}/estado` | Cambiar estado |
| PUT | `/api/semaforos/{id}/tiempos` | Configurar tiempos |
| POST | `/api/ciclos/iniciar` | Iniciar ciclo automático |
| POST | `/api/ciclos/detener` | Detener ciclo automático |
| GET | `/api/ciclos/estado` | Estado del ciclo |
| GET | `/api/ciclos/historial` | Historial de cambios |
| GET | `/api/dashboard` | Dashboard completo |

## WebSocket

Conectar a: `ws://localhost:8000/ws`

Tipos de mensajes recibidos:
- `estado_inicial` — Estado completo al conectar
- `estado_live` — Tick cada segundo con estados y timers
- `actualizacion_ciclo` — Cuando un semáforo cambia de estado
- `semaforos_generados` — Tras generar semáforos
- `estado_cambiado` — Cambio manual de estado
- `ciclo_detenido` — Ciclo detenido

## Flujo de Uso

1. Abrir el Dashboard
2. Click **"⚡ Generar Semáforos"** → Genera semáforos para todas las intersecciones
3. Click **"▶ Iniciar Ciclo Auto"** → Comienza el ciclo automático verde→amarillo→rojo
4. Ver los semáforos cambiar en tiempo real en los mapas y la tabla
5. Usar los botones V/A/R para control manual por semáforo
6. Click ✏️ para configurar tiempos y modo de cada semáforo

## Variables de Entorno (.env)

```env
SUPABASE_URL=https://kfuddhujgzawigqgmxpd.supabase.co
SUPABASE_KEY=<service_role_key>
MAPAS_API_URL=https://tecnologia-atkj.onrender.com/api/mapas
```
