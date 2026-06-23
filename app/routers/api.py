import logging
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    EstadoSemaforo,
    SemaforoResponse,
    SemaforoCreate,
    SemaforoEstadoUpdate,
    SemaforoTiemposUpdate,
    MensajeResponse,
    SemaforoBulkDeleteRequest,
    SemaforoDeleteResponse,
    GenerarSemaforosRequest,
    GenerarSemaforosResponse,
)
import app.services.semaforo as semaforo_svc
import app.services.ciclo as ciclo_svc
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA — SEMAFOROS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/api/semaforos",
    response_model=List[SemaforoResponse],
    summary="Listar semáforos",
    description="Devuelve todos los semáforos registrados en el sistema. "
                "Un sistema externo puede usar este endpoint para mostrar automáticamente "
                "los semáforos en su propia interfaz.",
    tags=["Semáforos"],
)
async def listar_semaforos(activo: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo")):
    try:
        semaforos = await semaforo_svc.listar_semaforos()
        if activo is not None:
            semaforos = [s for s in semaforos if s.get("activo") is activo]
        return semaforos
    except Exception as e:
        logger.error(f"[API] Error listando semáforos: {e}")
        raise HTTPException(500, f"Error al listar semáforos: {e}")


@router.get(
    "/api/semaforos/{semaforo_id}",
    response_model=SemaforoResponse,
    summary="Consultar semáforo específico",
    description="Obtiene la información completa de un semáforo por su ID.",
    tags=["Semáforos"],
)
async def obtener_semaforo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    return sem


@router.get(
    "/api/semaforos/{semaforo_id}/estado",
    summary="Consultar estado actual",
    description="Devuelve el estado actual de un semáforo (verde, amarillo o rojo) "
                "y su modo de operación (automático o manual).",
    tags=["Semáforos"],
)
async def consultar_estado_actual(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    return {
        "id": semaforo_id,
        "estado": sem.get("estado"),
        "modo": sem.get("modo"),
        "activo": sem.get("activo"),
        "direccion": sem.get("direccion"),
        "interseccion_id": sem.get("interseccion_id"),
    }


@router.get(
    "/api/semaforos/{semaforo_id}/tiempo",
    summary="Consultar tiempo restante",
    description="Indica cuántos segundos faltan para que el semáforo cambie de estado. "
                "Si el ciclo automático no está activo, devuelve null.",
    tags=["Semáforos"],
)
async def consultar_tiempo_restante(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")

    ticks = ciclo_svc.get_ticks()
    tick = ticks.get(semaforo_id)
    if tick:
        remaining = max(0, tick["duracion"] - (time.time() - tick["inicio_estado"]))
        return {
            "id": semaforo_id,
            "estado": tick["estado"],
            "tiempo_restante_segundos": round(remaining, 1),
            "duracion_total_segundos": tick["duracion"],
        }

    return {
        "id": semaforo_id,
        "estado": sem.get("estado"),
        "tiempo_restante_segundos": None,
        "duracion_total_segundos": None,
        "nota": "El ciclo automático no está activo o el semáforo no está en ciclo",
    }


@router.put(
    "/api/semaforos/{semaforo_id}/estado",
    summary="Cambiar estado",
    description="Cambia manualmente el estado de un semáforo (verde, amarillo, rojo) "
                "y opcionalmente su modo de operación.",
    tags=["Semáforos"],
)
async def cambiar_estado(semaforo_id: int, body: SemaforoEstadoUpdate):
    logger.info(f"[API] PUT sem/{semaforo_id} estado={body.estado} modo={body.modo}")
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    try:
        result = await semaforo_svc.actualizar_estado(
            semaforo_id, body.estado.value, body.modo.value if body.modo else None
        )
        await manager.broadcast({
            "tipo": "estado_cambiado",
            "semaforo_id": semaforo_id,
            "estado": body.estado.value,
            "modo": body.modo.value if body.modo else sem.get("modo"),
        })
        return result
    except Exception as e:
        logger.error(f"[API] Error cambiando estado: {e}")
        raise HTTPException(500, f"Error: {e}")


@router.put(
    "/api/semaforos/{semaforo_id}/tiempos",
    summary="Configurar tiempos",
    description="Ajusta los tiempos de duración de cada estado del semáforo "
                "(verde, amarillo y rojo) en segundos.",
    tags=["Semáforos"],
)
async def configurar_tiempos(semaforo_id: int, body: SemaforoTiemposUpdate):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    try:
        result = await semaforo_svc.actualizar_tiempos(
            semaforo_id, body.tiempo_verde, body.tiempo_amarillo, body.tiempo_rojo
        )
        await manager.broadcast({
            "tipo": "tiempos_actualizados",
            "semaforo_id": semaforo_id,
            "tiempos": body.model_dump(),
        })
        return result
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.put(
    "/api/semaforos/{semaforo_id}/activar",
    summary="Activar semáforo",
    description="Activa un semáforo para que participe en el ciclo automático.",
    tags=["Semáforos"],
)
async def activar_semaforo_endpoint(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    try:
        result = await semaforo_svc.activar_semaforo(semaforo_id)
        await manager.broadcast({"tipo": "semaforo_activado", "semaforo_id": semaforo_id})
        return {"id": semaforo_id, "activo": True, "mensaje": "Semáforo activado"}
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.put(
    "/api/semaforos/{semaforo_id}/desactivar",
    summary="Desactivar semáforo",
    description="Desactiva un semáforo para que no participe en el ciclo automático.",
    tags=["Semáforos"],
)
async def desactivar_semaforo_endpoint(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    try:
        result = await semaforo_svc.desactivar_semaforo(semaforo_id)
        await manager.broadcast({"tipo": "semaforo_desactivado", "semaforo_id": semaforo_id})
        return {"id": semaforo_id, "activo": False, "mensaje": "Semáforo desactivado"}
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.post(
    "/api/semaforos",
    response_model=SemaforoResponse,
    summary="Crear semáforo",
    description="Crea un nuevo semáforo manualmente en el sistema.",
    tags=["Semáforos"],
)
async def crear_semaforo(body: SemaforoCreate):
    try:
        nuevo = await semaforo_svc.crear_semaforo(body.model_dump())
        await manager.broadcast({"tipo": "semaforo_creado", "semaforo": nuevo})
        return nuevo
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.delete(
    "/api/semaforos/{semaforo_id}",
    response_model=SemaforoDeleteResponse,
    summary="Eliminar semáforo",
    description="Elimina un semáforo del sistema por su ID.",
    tags=["Semáforos"],
)
async def eliminar_semaforo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    try:
        ok = await semaforo_svc.eliminar_semaforo(semaforo_id)
        await manager.broadcast({"tipo": "semaforo_eliminado", "semaforo_id": semaforo_id})
        return SemaforoDeleteResponse(eliminados=1 if ok else 0, mensaje="Semáforo eliminado")
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.post(
    "/api/semaforos/eliminar",
    response_model=SemaforoDeleteResponse,
    summary="Eliminar varios semáforos",
    description="Elimina múltiples semáforos enviando una lista de IDs.",
    tags=["Semáforos"],
)
async def eliminar_varios_semaforos(body: SemaforoBulkDeleteRequest):
    try:
        n = await semaforo_svc.eliminar_semaforos(body.ids)
        await manager.broadcast({"tipo": "semaforos_eliminados", "ids": body.ids})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f"{n} semáforos eliminados")
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.delete(
    "/api/semaforos/todos/confirmar",
    response_model=SemaforoDeleteResponse,
    summary="Eliminar todos los semáforos",
    description="Elimina todos los semáforos del sistema. Usar con precaución.",
    tags=["Semáforos"],
)
async def eliminar_todos_semaforos():
    try:
        n = await semaforo_svc.eliminar_todos_semaforos()
        await manager.broadcast({"tipo": "semaforos_eliminados", "todos": True})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f"{n} semáforos eliminados")
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA — CICLOS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/api/ciclos/iniciar",
    response_model=MensajeResponse,
    summary="Iniciar ciclo automático",
    description="Inicia el ciclo automático de todos los semáforos activos.",
    tags=["Ciclos"],
)
async def iniciar_ciclo():
    logger.info("[API] POST /api/ciclos/iniciar")
    try:
        result = await ciclo_svc.iniciar_ciclo(broadcast_fn=manager.broadcast)
        return MensajeResponse(mensaje=result["mensaje"])
    except Exception as e:
        logger.error(f"[API] Error iniciando ciclo: {e}")
        raise HTTPException(500, str(e)[:200])


@router.post(
    "/api/ciclos/detener",
    response_model=MensajeResponse,
    summary="Detener ciclo automático",
    description="Detiene el ciclo automático y congela los estados actuales.",
    tags=["Ciclos"],
)
async def detener_ciclo():
    logger.info("[API] POST /api/ciclos/detener")
    try:
        result = await ciclo_svc.detener_ciclo(broadcast_fn=manager.broadcast)
        return MensajeResponse(mensaje=result["mensaje"])
    except Exception as e:
        logger.error(f"[API] Error deteniendo ciclo: {e}")
        raise HTTPException(500, str(e))


@router.get(
    "/api/ciclos/estado",
    summary="Consultar estado del ciclo",
    description="Indica si el ciclo automático está activo y cuántos semáforos están siendo controlados.",
    tags=["Ciclos"],
)
async def estado_ciclo():
    return {
        "ciclo_activo": ciclo_svc.esta_activo(),
        "semaforos_en_ciclo": len(ciclo_svc.get_ticks()),
        "modo_sistema": "automatico" if ciclo_svc.esta_activo() else "manual",
    }


@router.get(
    "/api/ciclos/historial",
    summary="Historial de ciclos",
    description="Devuelve el historial de cambios de estado registrados en la base de datos.",
    tags=["Ciclos"],
)
async def historial_ciclos(
    limit: int = Query(100, ge=1, le=500, description="Cantidad máxima de registros"),
    estado: Optional[EstadoSemaforo] = Query(None, description="Filtrar por estado"),
):
    from app.database import supabase_get
    try:
        params = {"select": "*", "order": "fecha.desc", "limit": str(limit)}
        if estado:
            params["estado"] = f"eq.{estado.value}"
        return await supabase_get("ciclos", params)
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA — SISTEMA
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/api/estadisticas",
    summary="Obtener estadísticas generales",
    description="Resumen del sistema: cantidad de semáforos totales, activos, por estado "
                "y estado del ciclo automático. Ideal para paneles de monitoreo externos.",
    tags=["Sistema"],
)
async def obtener_estadisticas():
    try:
        dashboard = await semaforo_svc.obtener_dashboard()
        stats = dashboard.get("stats", {})
        return {
            "total_semaforos": stats.get("total_semaforos", 0),
            "semaforos_activos": stats.get("semaforos_activos", 0),
            "semaforos_verde": stats.get("semaforos_verde", 0),
            "semaforos_amarillo": stats.get("semaforos_amarillo", 0),
            "semaforos_rojo": stats.get("semaforos_rojo", 0),
            "ciclo_activo": stats.get("ciclo_activo", False),
            "modo_sistema": "automatico" if stats.get("ciclo_activo", False) else "manual",
        }
    except Exception as e:
        logger.error(f"[API] Estadísticas error: {e}")
        raise HTTPException(500, f"Error: {e}")


@router.get(
    "/api/dashboard",
    summary="Dashboard completo",
    description="Devuelve el dashboard completo con semáforos, estadísticas y estado del ciclo.",
    tags=["Sistema"],
)
async def obtener_dashboard():
    try:
        return await semaforo_svc.obtener_dashboard()
    except Exception as e:
        logger.error(f"[API] Dashboard error: {e}")
        raise HTTPException(500, f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS INTERNOS (ocultos de Swagger/OpenAPI)
# Módulos de Mapas y Vehículos — NO forman parte de la API pública,
# pero se mantienen para uso interno del dashboard y lógica del sistema.
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/mapas", include_in_schema=False)
async def _get_mapas():
    try:
        return await semaforo_svc.obtener_mapas()
    except Exception as e:
        raise HTTPException(502, f"Error al obtener mapas: {e}")


@router.get("/api/intersecciones", include_in_schema=False)
async def _get_intersecciones():
    try:
        return await semaforo_svc.obtener_intersecciones()
    except Exception as e:
        raise HTTPException(502, f"Error al obtener intersecciones: {e}")


@router.get("/api/intersecciones/{interseccion_id}/semaforos", include_in_schema=False)
async def _get_semaforos_interseccion(interseccion_id: str):
    try:
        return await semaforo_svc.listar_semaforos(interseccion_id=interseccion_id)
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.get("/api/semaforos/mapa/{clave}", include_in_schema=False)
async def _get_semaforos_mapa(clave: str):
    try:
        return await semaforo_svc.listar_semaforos(mapa_clave=clave)
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.delete("/api/semaforos/mapa/{clave}", include_in_schema=False)
async def _delete_semaforos_mapa(clave: str):
    try:
        n = await semaforo_svc.eliminar_semaforos_por_mapa(clave)
        await manager.broadcast({"tipo": "semaforos_eliminados", "mapa_clave": clave})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f"{n} semáforos eliminados del mapa {clave}")
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.get("/api/semaforos/{semaforo_id}/vehiculo", include_in_schema=False)
async def _get_decision_vehiculo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f"Semáforo {semaforo_id} no encontrado")
    estado = sem.get("estado", "rojo")
    avanzar = estado == "verde"
    razon = {
        "verde": "Semáforo en verde: avanzar",
        "amarillo": "Semáforo en amarillo: detenerse con precaución",
        "rojo": "Semáforo en rojo: detenerse",
    }.get(estado, "Estado desconocido")
    return {
        "id": semaforo_id,
        "estado": estado,
        "avanzar": avanzar,
        "razon": razon,
        "interseccion_id": sem.get("interseccion_id"),
        "direccion": sem.get("direccion"),
    }


# Alias internos mantenidos por compatibilidad (no visibles en Swagger)
@router.post("/api/semaforos/generar", response_model=GenerarSemaforosResponse, include_in_schema=False)
async def _post_generar_semaforos(req: GenerarSemaforosRequest = None):
    if req is None:
        req = GenerarSemaforosRequest()
    try:
        result = await semaforo_svc.generar_semaforos(req)
        await manager.broadcast({
            "tipo": "semaforos_generados",
            "semaforos_creados": result.semaforos_creados,
            "mapas": result.mapas_procesados,
        })
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


@router.put("/api/semaforos/{semaforo_id}/configuracion", include_in_schema=False)
async def _put_configuracion_alias(semaforo_id: int, body: SemaforoTiemposUpdate):
    return await configurar_tiempos(semaforo_id, body)


@router.post("/api/ciclo/iniciar", include_in_schema=False)
async def _post_iniciar_ciclo_alias():
    return await iniciar_ciclo()


@router.post("/api/ciclo/detener", include_in_schema=False)
async def _post_detener_ciclo_alias():
    return await detener_ciclo()
