"""
Script para crear las tablas en Supabase via REST API
Ejecutar una sola vez para inicializar la base de datos
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SERVICE_KEY:
    raise ValueError(
        "SUPABASE_URL y SUPABASE_KEY deben estar configuradas. "
        "Crea un archivo .env o exporta las variables de entorno."
    )

SQL_SETUP = """
-- Tabla semaforos
CREATE TABLE IF NOT EXISTS semaforos (
    id BIGSERIAL PRIMARY KEY,
    mapa_clave TEXT NOT NULL,
    interseccion_id TEXT NOT NULL,
    interseccion_nombre TEXT,
    pos_x INTEGER,
    pos_y INTEGER,
    direccion TEXT NOT NULL CHECK (direccion IN ('NS','SN','EO','OE')),
    estado TEXT NOT NULL DEFAULT 'rojo' CHECK (estado IN ('verde','amarillo','rojo')),
    tiempo_verde INTEGER NOT NULL DEFAULT 30,
    tiempo_amarillo INTEGER NOT NULL DEFAULT 5,
    tiempo_rojo INTEGER NOT NULL DEFAULT 30,
    activo BOOLEAN NOT NULL DEFAULT true,
    modo TEXT NOT NULL DEFAULT 'automatico' CHECK (modo IN ('automatico','manual')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tabla ciclos
CREATE TABLE IF NOT EXISTS ciclos (
    id BIGSERIAL PRIMARY KEY,
    semaforo_id BIGINT NOT NULL REFERENCES semaforos(id) ON DELETE CASCADE,
    estado TEXT NOT NULL CHECK (estado IN ('verde','amarillo','rojo')),
    duracion_segundos INTEGER,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tabla configuraciones
CREATE TABLE IF NOT EXISTS configuraciones (
    id BIGSERIAL PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    valor TEXT NOT NULL,
    descripcion TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_semaforos_mapa ON semaforos(mapa_clave);
CREATE INDEX IF NOT EXISTS idx_ciclos_semaforo ON ciclos(semaforo_id);
CREATE INDEX IF NOT EXISTS idx_ciclos_fecha ON ciclos(fecha DESC);

-- Configuraciones por defecto
INSERT INTO configuraciones (nombre, valor, descripcion) VALUES
    ('ciclo_activo', 'false', 'Indica si el ciclo automático está corriendo'),
    ('intervalo_ciclo', '1', 'Segundos entre actualizaciones del ciclo'),
    ('tiempo_verde_default', '30', 'Tiempo verde por defecto en segundos'),
    ('tiempo_amarillo_default', '5', 'Tiempo amarillo por defecto en segundos'),
    ('tiempo_rojo_default', '30', 'Tiempo rojo por defecto en segundos')
ON CONFLICT (nombre) DO NOTHING;

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS semaforos_updated_at ON semaforos;
CREATE TRIGGER semaforos_updated_at
    BEFORE UPDATE ON semaforos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
"""

def setup_db():
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json"
    }
    
    resp = httpx.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
        headers=headers,
        json={"query": SQL_SETUP},
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    print(resp.text[:500])

if __name__ == "__main__":
    setup_db()
