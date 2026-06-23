import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://kfuddhujgzawigqgmxpd.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtmdWRkaHVqZ3phd2lncWdteHBkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTgwMzY3NiwiZXhwIjoyMDk3Mzc5Njc2fQ.-pBlGbnK68Lb3Z8Yxm_Uhbx7YfI4oPhH8Ow6PuJLwoM")
MAPAS_API_URL = os.getenv("MAPAS_API_URL", "https://tecnologia-atkj.onrender.com/api/mapas")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

async def supabase_get(table: str, params: dict = None):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            params=params or {},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()

async def supabase_post(table: str, data: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            json=data,
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()

async def supabase_patch(table: str, filters: dict, data: dict):
    params = {k: f"eq.{v}" for k, v in filters.items()}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            params=params,
            json=data,
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()

async def supabase_delete(table: str, filters: dict):
    params = {k: f"eq.{v}" for k, v in filters.items()}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            params=params,
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()

async def supabase_delete_bulk(table: str, ids: list):
    if not ids:
        return []
    params = {"id": f"in.({','.join(map(str, ids))})"}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            params=params,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()

async def fetch_mapas():
    async with httpx.AsyncClient() as client:
        resp = await client.get(MAPAS_API_URL, timeout=20)
        resp.raise_for_status()
        return resp.json()

async def setup_tables():
    """Crea las tablas vía SQL usando el endpoint de Supabase"""
    sql = """
    CREATE TABLE IF NOT EXISTS semaforos (
        id BIGSERIAL PRIMARY KEY,
        mapa_clave TEXT NOT NULL,
        interseccion_id TEXT NOT NULL,
        interseccion_nombre TEXT,
        pos_x INTEGER,
        pos_y INTEGER,
        direccion TEXT NOT NULL DEFAULT 'NS',
        estado TEXT NOT NULL DEFAULT 'rojo',
        tiempo_verde INTEGER NOT NULL DEFAULT 30,
        tiempo_amarillo INTEGER NOT NULL DEFAULT 5,
        tiempo_rojo INTEGER NOT NULL DEFAULT 30,
        activo BOOLEAN NOT NULL DEFAULT true,
        modo TEXT NOT NULL DEFAULT 'automatico',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS ciclos (
        id BIGSERIAL PRIMARY KEY,
        semaforo_id BIGINT NOT NULL,
        estado TEXT NOT NULL,
        duracion_segundos INTEGER,
        fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS configuraciones (
        id BIGSERIAL PRIMARY KEY,
        nombre TEXT NOT NULL UNIQUE,
        valor TEXT NOT NULL,
        descripcion TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    INSERT INTO configuraciones (nombre, valor, descripcion) VALUES
        ('ciclo_activo', 'false', 'Estado del ciclo automático'),
        ('intervalo_ciclo', '1', 'Segundos entre ticks'),
        ('tiempo_verde_default', '30', 'Tiempo verde default'),
        ('tiempo_amarillo_default', '5', 'Tiempo amarillo default'),
        ('tiempo_rojo_default', '30', 'Tiempo rojo default')
    ON CONFLICT (nombre) DO NOTHING;
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            headers=HEADERS,
            json={"query": sql},
            timeout=30
        )
        return resp.status_code, resp.text
