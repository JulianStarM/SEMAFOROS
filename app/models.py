from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class EstadoSemaforo(str, Enum):
    verde = "verde"
    amarillo = "amarillo"
    rojo = "rojo"


class DireccionSemaforo(str, Enum):
    NS = "NS"
    SN = "SN"
    EO = "EO"
    OE = "OE"


class ModoSemaforo(str, Enum):
    automatico = "automatico"
    manual = "manual"


# ── Semáforo ──────────────────────────────────────────
class SemaforoBase(BaseModel):
    mapa_clave: str
    interseccion_id: str
    interseccion_nombre: Optional[str] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    direccion: DireccionSemaforo = DireccionSemaforo.NS
    estado: EstadoSemaforo = EstadoSemaforo.rojo
    tiempo_verde: int = Field(default=30, ge=5, le=300)
    tiempo_amarillo: int = Field(default=5, ge=3, le=30)
    tiempo_rojo: int = Field(default=30, ge=5, le=300)
    activo: bool = True
    modo: ModoSemaforo = ModoSemaforo.automatico


class SemaforoCreate(SemaforoBase):
    pass


class SemaforoResponse(SemaforoBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SemaforoEstadoUpdate(BaseModel):
    estado: EstadoSemaforo
    modo: Optional[ModoSemaforo] = None


class SemaforoTiemposUpdate(BaseModel):
    tiempo_verde: int = Field(ge=5, le=300)
    tiempo_amarillo: int = Field(ge=3, le=30)
    tiempo_rojo: int = Field(ge=5, le=300)


# ── Ciclo ────────────────────────────────────────────
class CicloResponse(BaseModel):
    id: int
    semaforo_id: int
    estado: EstadoSemaforo
    duracion_segundos: Optional[int] = None
    fecha: Optional[datetime] = None


# ── Configuración ────────────────────────────────────
class ConfiguracionResponse(BaseModel):
    id: int
    nombre: str
    valor: str
    descripcion: Optional[str] = None


# ── Intersección / Mapa ──────────────────────────────
class InterseccionInfo(BaseModel):
    interseccion_id: str
    nombre: str
    pos_x: int
    pos_y: int
    semaforos: List[SemaforoResponse] = []


class MapaInfo(BaseModel):
    clave: str
    nombre: str
    color_tema: str
    width: int
    height: int
    total_intersecciones: int
    total_semaforos: int
    intersecciones: List[InterseccionInfo] = []


# ── Dashboard ────────────────────────────────────────
class DashboardStats(BaseModel):
    total_mapas: int
    total_intersecciones: int
    total_semaforos: int
    semaforos_activos: int
    semaforos_verde: int
    semaforos_amarillo: int
    semaforos_rojo: int
    ciclo_activo: bool
    mapas: List[MapaInfo] = []


# ── Respuestas genéricas ──────────────────────────────
class MensajeResponse(BaseModel):
    mensaje: str
    detalle: Optional[str] = None


class GenerarSemaforosRequest(BaseModel):
    mapa_clave: Optional[str] = None  # None = todos los mapas
    tiempo_verde: int = Field(default=30, ge=5, le=300)
    tiempo_amarillo: int = Field(default=5, ge=3, le=30)
    tiempo_rojo: int = Field(default=30, ge=5, le=300)
    regenerar: bool = False  # Si True, elimina los existentes primero


class GenerarSemaforosResponse(BaseModel):
    semaforos_creados: int
    semaforos_existentes: int
    mapas_procesados: List[str]
    detalle: List[str] = []


class SemaforoBulkDeleteRequest(BaseModel):
    ids: List[int]


class SemaforoDeleteResponse(BaseModel):
    eliminados: int
    mensaje: str
