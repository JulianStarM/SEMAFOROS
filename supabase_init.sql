-- ════════════════════════════════════════════════════════════════
-- SISTEMA INTELIGENTE DE GESTIÓN DE SEMÁFOROS
-- Ejecutar este script en el SQL Editor de Supabase
-- URL: https://kfuddhujgzawigqgmxpd.supabase.co
-- ════════════════════════════════════════════════════════════════

-- ── Tabla principal de semáforos ──────────────────────────────
CREATE TABLE IF NOT EXISTS semaforos (
    id          BIGSERIAL PRIMARY KEY,
    mapa_clave          TEXT NOT NULL,
    interseccion_id     TEXT NOT NULL,
    interseccion_nombre TEXT,
    pos_x       INTEGER,
    pos_y       INTEGER,
    direccion   TEXT NOT NULL DEFAULT 'NS'
                    CHECK (direccion IN ('NS','SN','EO','OE')),
    estado      TEXT NOT NULL DEFAULT 'rojo'
                    CHECK (estado IN ('verde','amarillo','rojo')),
    tiempo_verde    INTEGER NOT NULL DEFAULT 30,
    tiempo_amarillo INTEGER NOT NULL DEFAULT 5,
    tiempo_rojo     INTEGER NOT NULL DEFAULT 30,
    activo      BOOLEAN  NOT NULL DEFAULT TRUE,
    modo        TEXT NOT NULL DEFAULT 'automatico'
                    CHECK (modo IN ('automatico','manual')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Tabla de historial de ciclos ──────────────────────────────
CREATE TABLE IF NOT EXISTS ciclos (
    id              BIGSERIAL PRIMARY KEY,
    semaforo_id     BIGINT NOT NULL
                        REFERENCES semaforos(id) ON DELETE CASCADE,
    estado          TEXT NOT NULL
                        CHECK (estado IN ('verde','amarillo','rojo')),
    duracion_segundos INTEGER,
    fecha           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Tabla de configuraciones del sistema ─────────────────────
CREATE TABLE IF NOT EXISTS configuraciones (
    id          BIGSERIAL PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE,
    valor       TEXT NOT NULL,
    descripcion TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Índices de rendimiento ────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_semaforos_mapa
    ON semaforos(mapa_clave);

CREATE INDEX IF NOT EXISTS idx_semaforos_interseccion
    ON semaforos(mapa_clave, interseccion_id);

CREATE INDEX IF NOT EXISTS idx_ciclos_semaforo
    ON ciclos(semaforo_id);

CREATE INDEX IF NOT EXISTS idx_ciclos_fecha
    ON ciclos(fecha DESC);

-- ── Configuraciones por defecto ───────────────────────────────
INSERT INTO configuraciones (nombre, valor, descripcion) VALUES
    ('ciclo_activo',          'false', 'Indica si el ciclo automático está corriendo'),
    ('intervalo_ciclo',       '1',     'Segundos entre ticks del ciclo'),
    ('tiempo_verde_default',  '30',    'Tiempo verde por defecto en segundos'),
    ('tiempo_amarillo_default','5',    'Tiempo amarillo por defecto en segundos'),
    ('tiempo_rojo_default',   '30',    'Tiempo rojo por defecto en segundos')
ON CONFLICT (nombre) DO NOTHING;

-- ── Trigger auto-update de updated_at ────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS semaforos_updated_at ON semaforos;
CREATE TRIGGER semaforos_updated_at
    BEFORE UPDATE ON semaforos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ── RLS: deshabilitar para uso con service_role ───────────────
-- (La app usa service_role key, no se necesita RLS)
ALTER TABLE semaforos      DISABLE ROW LEVEL SECURITY;
ALTER TABLE ciclos         DISABLE ROW LEVEL SECURITY;
ALTER TABLE configuraciones DISABLE ROW LEVEL SECURITY;

-- ════════════════════════════════════════════════════════════════
-- FIN DEL SCRIPT
-- ════════════════════════════════════════════════════════════════
