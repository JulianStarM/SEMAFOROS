import logging
import time
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models import (
    SemaforoResponse, SemaforoCreate, SemaforoEstadoUpdate, SemaforoTiemposUpdate,
    GenerarSemaforosRequest, GenerarSemaforosResponse, MensajeResponse,
    SemaforoBulkDeleteRequest, SemaforoDeleteResponse
)
import app.services.semaforo as semaforo_svc
import app.services.ciclo as ciclo_svc
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Mapas ──────────────────────────────────────────────────────────────────

@router.get('/api/mapas', summary='Obtener todos los mapas', tags=['Mapas'])
async def get_mapas():
    try:
        return await semaforo_svc.obtener_mapas()
    except Exception as e:
        raise HTTPException(502, f'Error al obtener mapas: {e}')


# ─── Semáforos ─────────────────────────────────────────────────────────────

@router.post('/api/semaforos/generar', response_model=GenerarSemaforosResponse, summary='Generar semáforos', tags=['Semáforos'])
async def post_generar_semaforos(req: GenerarSemaforosRequest = None):
    if req is None:
        req = GenerarSemaforosRequest()
    try:
        result = await semaforo_svc.generar_semaforos(req)
        await manager.broadcast({
            'tipo': 'semaforos_generados',
            'semaforos_creados': result.semaforos_creados,
            'mapas': result.mapas_procesados
        })
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.get('/api/semaforos', summary='Listar semáforos', tags=['Semáforos'])
async def get_semaforos(mapa_clave: Optional[str] = Query(None)):
    try:
        return await semaforo_svc.listar_semaforos(mapa_clave)
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.get('/api/semaforos/{semaforo_id}', summary='Obtener semáforo', tags=['Semáforos'])
async def get_semaforo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    return sem


@router.get('/api/semaforos/mapa/{clave}', summary='Semáforos por mapa', tags=['Semáforos'])
async def get_semaforos_mapa(clave: str):
    try:
        return await semaforo_svc.listar_semaforos(mapa_clave=clave)
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.put('/api/semaforos/{semaforo_id}/estado', summary='Cambiar estado', tags=['Semáforos'])
async def put_semaforo_estado(semaforo_id: int, body: SemaforoEstadoUpdate):
    logger.info(f'[API] PUT sem/{semaforo_id} estado={body.estado} modo={body.modo}')
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    try:
        result = await semaforo_svc.actualizar_estado(semaforo_id, body.estado.value, body.modo.value if body.modo else None)
        await manager.broadcast({
            'tipo': 'estado_cambiado',
            'semaforo_id': semaforo_id,
            'estado': body.estado.value,
            'mapa_clave': sem['mapa_clave']
        })
        return result
    except Exception as e:
        logger.error(f'[API] Error: {e}')
        raise HTTPException(500, f'Error: {e}')


@router.put('/api/semaforos/{semaforo_id}/tiempos', summary='Configurar tiempos', tags=['Semáforos'])
async def put_semaforo_tiempos(semaforo_id: int, body: SemaforoTiemposUpdate):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    try:
        result = await semaforo_svc.actualizar_tiempos(semaforo_id, body.tiempo_verde, body.tiempo_amarillo, body.tiempo_rojo)
        await manager.broadcast({'tipo': 'tiempos_actualizados', 'semaforo_id': semaforo_id, 'tiempos': body.model_dump()})
        return result
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.post('/api/semaforos', response_model=SemaforoResponse, summary='Crear semáforo manual', tags=['Semáforos'])
async def post_crear_semaforo(body: SemaforoCreate):
    try:
        nuevo = await semaforo_svc.crear_semaforo(body.model_dump())
        await manager.broadcast({'tipo': 'semaforo_creado', 'semaforo': nuevo})
        return nuevo
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.delete('/api/semaforos/{semaforo_id}', response_model=SemaforoDeleteResponse, summary='Eliminar semáforo', tags=['Semáforos'])
async def delete_semaforo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    try:
        ok = await semaforo_svc.eliminar_semaforo(semaforo_id)
        await manager.broadcast({'tipo': 'semaforo_eliminado', 'semaforo_id': semaforo_id, 'mapa_clave': sem['mapa_clave']})
        return SemaforoDeleteResponse(eliminados=1 if ok else 0, mensaje='Semáforo eliminado')
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.post('/api/semaforos/eliminar', response_model=SemaforoDeleteResponse, summary='Eliminar varios semáforos', tags=['Semáforos'])
async def post_eliminar_semaforos(body: SemaforoBulkDeleteRequest):
    try:
        n = await semaforo_svc.eliminar_semaforos(body.ids)
        await manager.broadcast({'tipo': 'semaforos_eliminados', 'ids': body.ids})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f'{n} semáforos eliminados')
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.delete('/api/semaforos/mapa/{clave}', response_model=SemaforoDeleteResponse, summary='Eliminar semáforos de un mapa', tags=['Semáforos'])
async def delete_semaforos_mapa(clave: str):
    try:
        n = await semaforo_svc.eliminar_semaforos_por_mapa(clave)
        await manager.broadcast({'tipo': 'semaforos_eliminados', 'mapa_clave': clave})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f'{n} semáforos eliminados del mapa {clave}')
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.delete('/api/semaforos/todos/confirmar', response_model=SemaforoDeleteResponse, summary='Eliminar TODOS los semáforos', tags=['Semáforos'])
async def delete_todos_semaforos():
    try:
        n = await semaforo_svc.eliminar_todos_semaforos()
        await manager.broadcast({'tipo': 'semaforos_eliminados', 'todos': True})
        return SemaforoDeleteResponse(eliminados=n, mensaje=f'{n} semáforos eliminados')
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


# ─── Ciclos ─────────────────────────────────────────────────────────────────

@router.post('/api/ciclos/iniciar', response_model=MensajeResponse, summary='Iniciar ciclo automático', tags=['Ciclos'])
async def post_iniciar_ciclo():
    logger.info('[API] POST /api/ciclos/iniciar')
    try:
        result = await ciclo_svc.iniciar_ciclo(broadcast_fn=manager.broadcast)
        logger.info(f'[API] OK: {result}')
        return MensajeResponse(mensaje=result['mensaje'])
    except Exception as e:
        logger.error(f'[API] Error ciclo: {e}')
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e)[:200])


@router.post('/api/ciclos/detener', response_model=MensajeResponse, summary='Detener ciclo automático', tags=['Ciclos'])
async def post_detener_ciclo():
    logger.info('[API] POST /api/ciclos/detener')
    try:
        result = await ciclo_svc.detener_ciclo(broadcast_fn=manager.broadcast)
        return MensajeResponse(mensaje=result['mensaje'])
    except Exception as e:
        logger.error(f'[API] Error detener: {e}')
        raise HTTPException(500, str(e))


@router.get('/api/ciclos/estado', summary='Estado del ciclo', tags=['Ciclos'])
async def get_ciclo_estado():
    return {
        'activo': ciclo_svc.esta_activo(),
        'semaforos_en_ciclo': len(ciclo_svc.get_ticks())
    }


@router.get('/api/ciclos/historial', summary='Historial de ciclos', tags=['Ciclos'])
async def get_historial(limit: int = Query(100, ge=1, le=500), estado: Optional[str] = Query(None)):
    from app.database import supabase_get
    try:
        params = {
            'select': '*',
            'order': 'fecha.desc',
            'limit': str(limit)
        }
        if estado:
            params['estado'] = f'eq.{estado}'
        return await supabase_get('ciclos', params)
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


# ─── Intersecciones ─────────────────────────────────────────────────────────

@router.get('/api/intersecciones', summary='Listar intersecciones desde API de mapas', tags=['Intersecciones'])
async def get_intersecciones():
    try:
        return await semaforo_svc.obtener_intersecciones()
    except Exception as e:
        raise HTTPException(502, f'Error al obtener intersecciones: {e}')


@router.get('/api/intersecciones/{interseccion_id}/semaforos', summary='Semáforos de una intersección', tags=['Intersecciones'])
async def get_semaforos_interseccion(interseccion_id: str):
    try:
        return await semaforo_svc.listar_semaforos(interseccion_id=interseccion_id)
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


# ─── Alias profesionales para módulos externos ──────────────────────────────

@router.get('/api/semaforos/{semaforo_id}/estado', summary='Consultar estado actual', tags=['Semáforos'])
async def get_semaforo_estado(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    return {
        'id': semaforo_id,
        'estado': sem.get('estado'),
        'modo': sem.get('modo'),
        'mapa_clave': sem.get('mapa_clave'),
        'interseccion_id': sem.get('interseccion_id'),
        'direccion': sem.get('direccion')
    }


@router.get('/api/semaforos/{semaforo_id}/tiempo', summary='Tiempo restante del semáforo', tags=['Semáforos'])
async def get_semaforo_tiempo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    ticks = ciclo_svc.get_ticks()
    tick = ticks.get(semaforo_id)
    if tick:
        remaining = max(0, tick['duracion'] - (time.time() - tick['inicio_estado']))
        return {
            'id': semaforo_id,
            'estado': tick['estado'],
            'tiempo_restante': round(remaining, 1),
            'duracion_total': tick['duracion']
        }
    return {
        'id': semaforo_id,
        'estado': sem.get('estado'),
        'tiempo_restante': None,
        'duracion_total': None,
        'nota': 'El ciclo automático no está activo o el semáforo no está en ciclo'
    }


@router.put('/api/semaforos/{semaforo_id}/configuracion', summary='Configurar tiempos (alias profesional)', tags=['Semáforos'])
async def put_semaforo_configuracion(semaforo_id: int, body: SemaforoTiemposUpdate):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    try:
        result = await semaforo_svc.actualizar_tiempos(semaforo_id, body.tiempo_verde, body.tiempo_amarillo, body.tiempo_rojo)
        await manager.broadcast({'tipo': 'tiempos_actualizados', 'semaforo_id': semaforo_id, 'tiempos': body.model_dump()})
        return result
    except Exception as e:
        raise HTTPException(500, f'Error: {e}')


@router.get('/api/semaforos/{semaforo_id}/vehiculo', summary='Decisión para vehículos', tags=['Vehículos'])
async def get_semaforo_decision_vehiculo(semaforo_id: int):
    sem = await semaforo_svc.obtener_semaforo(semaforo_id)
    if not sem:
        raise HTTPException(404, f'Semáforo {semaforo_id} no encontrado')
    estado = sem.get('estado', 'rojo')
    avanzar = estado == 'verde'
    razon = {
        'verde': 'Semáforo en verde: avanzar',
        'amarillo': 'Semáforo en amarillo: detenerse con precaución',
        'rojo': 'Semáforo en rojo: detenerse'
    }.get(estado, 'Estado desconocido')
    return {
        'id': semaforo_id,
        'estado': estado,
        'avanzar': avanzar,
        'razon': razon,
        'interseccion_id': sem.get('interseccion_id'),
        'direccion': sem.get('direccion')
    }


@router.post('/api/ciclo/iniciar', response_model=MensajeResponse, summary='Iniciar ciclo (alias profesional)', tags=['Ciclos'])
async def post_iniciar_ciclo_alias():
    return await post_iniciar_ciclo()


@router.post('/api/ciclo/detener', response_model=MensajeResponse, summary='Detener ciclo (alias profesional)', tags=['Ciclos'])
async def post_detener_ciclo_alias():
    return await post_detener_ciclo()


@router.get('/api/estadisticas', summary='Estadísticas generales del sistema', tags=['Dashboard'])
async def get_estadisticas():
    try:
        dashboard = await semaforo_svc.obtener_dashboard()
        stats = dashboard.get('stats', {})
        return {
            'total_mapas': stats.get('total_mapas', 0),
            'total_intersecciones': stats.get('total_intersecciones', 0),
            'total_semaforos': stats.get('total_semaforos', 0),
            'semaforos_activos': stats.get('semaforos_activos', 0),
            'semaforos_verde': stats.get('semaforos_verde', 0),
            'semaforos_amarillo': stats.get('semaforos_amarillo', 0),
            'semaforos_rojo': stats.get('semaforos_rojo', 0),
            'ciclo_activo': stats.get('ciclo_activo', False)
        }
    except Exception as e:
        logger.error(f'[API] Estadísticas error: {e}')
        raise HTTPException(500, f'Error: {e}')


# ─── Dashboard ──────────────────────────────────────────────────────────────

@router.get('/api/dashboard', summary='Dashboard completo', tags=['Dashboard'])
async def get_dashboard():
    try:
        return await semaforo_svc.obtener_dashboard()
    except Exception as e:
        logger.error(f'[API] Dashboard error: {e}')
        raise HTTPException(500, f'Error: {e}')
