import asyncio
import logging
import time
from typing import List, Optional, Dict

from app.models import EstadoSemaforo, DireccionSemaforo, GenerarSemaforosRequest, GenerarSemaforosResponse
from app.database import supabase_get, supabase_post, supabase_patch, supabase_delete, supabase_delete_bulk

logger = logging.getLogger(__name__)

DIRECCIONES_POR_INTERSECCION = [
    DireccionSemaforo.NS,
    DireccionSemaforo.SN,
    DireccionSemaforo.EO,
    DireccionSemaforo.OE,
]

_MAPAS_CACHE: Optional[list] = None
_MAPAS_CACHE_TS: float = 0
_MAPAS_CACHE_TTL = 60


def _gen_int_id(clave: str, pos: list, idx: int) -> str:
    return f'{clave}-int-{idx}-{pos[0]}-{pos[1]}'


async def _get_mapas_cached():
    global _MAPAS_CACHE, _MAPAS_CACHE_TS
    now = time.time()
    if _MAPAS_CACHE and (now - _MAPAS_CACHE_TS) < _MAPAS_CACHE_TTL:
        return _MAPAS_CACHE
    from app.database import fetch_mapas
    data = await fetch_mapas()
    _MAPAS_CACHE = data
    _MAPAS_CACHE_TS = now
    return data


def invalidate_mapas_cache():
    global _MAPAS_CACHE, _MAPAS_CACHE_TS
    _MAPAS_CACHE = None
    _MAPAS_CACHE_TS = 0


async def obtener_mapas():
    return await _get_mapas_cached()


async def generar_semaforos(req: GenerarSemaforosRequest) -> GenerarSemaforosResponse:
    logger.info(f'[SEM] Inicio gen: mapa={req.mapa_clave}, regen={req.regenerar}')
    t0 = time.time()
    mapas = await _get_mapas_cached()
    logger.info(f'[SEM] Mapas cargados: {len(mapas)}')

    if req.mapa_clave:
        mapas = [m for m in mapas if m['clave'] == req.mapa_clave]
        if not mapas:
            raise ValueError(f"Mapa '{req.mapa_clave}' no encontrado")

    creados = 0
    existentes = 0
    procesados = []
    detalle = []

    existing_cache = {}
    if not req.regenerar:
        try:
            all_existing = await supabase_get('semaforos', {'select': 'mapa_clave,interseccion_id,direccion'})
            for s in all_existing:
                key = (s['mapa_clave'], s['interseccion_id'], s['direccion'])
                existing_cache[key] = True
            logger.info(f'[SEM] Existentes: {len(existing_cache)}')
        except Exception as e:
            logger.warning(f'[SEM] Error existentes: {e}')

    for mapa in mapas:
        clave = mapa['clave']
        intersecciones = mapa.get('config', {}).get('intersecciones', [])
        logger.info(f'[SEM] Mapa {clave}: {len(intersecciones)} intersecciones')

        if req.regenerar:
            try:
                existentes_db = await supabase_get('semaforos', {'mapa_clave': f'eq.{clave}', 'select': 'id'})
                ids = [s['id'] for s in existentes_db]
                if ids:
                    logger.info(f'[SEM] Delete bulk: {len(ids)}')
                    await supabase_delete_bulk('semaforos', ids)
            except Exception as e:
                logger.warning(f'[SEM] Error delete: {e}')

        nuevos_batch = []
        for idx, inter in enumerate(intersecciones):
            int_id = _gen_int_id(clave, inter['pos'], idx)
            int_nombre = inter.get('nombre', f'Int {idx+1}').replace('\n', ' ')

            for dir_sem in DIRECCIONES_POR_INTERSECCION:
                key = (clave, int_id, dir_sem.value)
                if not req.regenerar and key in existing_cache:
                    existentes += 1
                    continue

                estado_inicial = EstadoSemaforo.verde.value if dir_sem in (DireccionSemaforo.NS, DireccionSemaforo.SN) else EstadoSemaforo.rojo.value
                nuevo = {
                    'mapa_clave': clave,
                    'interseccion_id': int_id,
                    'interseccion_nombre': int_nombre,
                    'pos_x': inter['pos'][0],
                    'pos_y': inter['pos'][1],
                    'direccion': dir_sem.value,
                    'estado': estado_inicial,
                    'tiempo_verde': req.tiempo_verde,
                    'tiempo_amarillo': req.tiempo_amarillo,
                    'tiempo_rojo': req.tiempo_rojo,
                    'activo': True,
                    'modo': 'automatico'
                }
                nuevos_batch.append(nuevo)

        logger.info(f'[SEM] Insertando {len(nuevos_batch)} sem for {clave}')
        if nuevos_batch:
            CHUNK = 50
            for i in range(0, len(nuevos_batch), CHUNK):
                chunk = nuevos_batch[i:i+CHUNK]
                results = await asyncio.gather(
                    *[supabase_post('semaforos', item) for item in chunk],
                    return_exceptions=True
                )
                for j, r in enumerate(results):
                    if isinstance(r, Exception):
                        detalle.append(f'Error: {chunk[j]["mapa_clave"]} | {str(r)[:80]}')
                    else:
                        creados += 1

        procesados.append(clave)

    invalidate_mapas_cache()
    logger.info(f'[SEM] Fin: creados={creados}, exist={existentes}, time={time.time()-t0:.1f}s')

    return GenerarSemaforosResponse(
        semaforos_creados=creados,
        semaforos_existentes=existentes,
        mapas_procesados=procesados,
        detalle=detalle
    )


async def listar_semaforos(mapa_clave: Optional[str] = None, interseccion_id: Optional[str] = None) -> List[Dict]:
    params = {'select': '*', 'order': 'mapa_clave.asc,interseccion_id.asc'}
    if mapa_clave:
        params['mapa_clave'] = f'eq.{mapa_clave}'
    if interseccion_id:
        params['interseccion_id'] = f'eq.{interseccion_id}'
    return await supabase_get('semaforos', params)


async def obtener_semaforo(semaforo_id: int) -> Optional[Dict]:
    result = await supabase_get('semaforos', {'id': f'eq.{semaforo_id}', 'select': '*'})
    return result[0] if result else None


async def actualizar_estado(semaforo_id: int, estado: str, modo: Optional[str] = None) -> Dict:
    logger.info(f'[SEM] Update estado: id={semaforo_id}, estado={estado}, modo={modo}')
    data = {'estado': estado}
    if modo:
        data['modo'] = modo
    result = await supabase_patch('semaforos', {'id': semaforo_id}, data)

    from app.services.ciclo import _TICK_COUNTERS
    if semaforo_id in _TICK_COUNTERS:
        tick = _TICK_COUNTERS[semaforo_id]
        sem_ref = tick.get('sem') or {}
        dur_map = {
            'verde': float(sem_ref.get('tiempo_verde', 30)),
            'amarillo': float(sem_ref.get('tiempo_amarillo', 5)),
            'rojo': float(sem_ref.get('tiempo_rojo', 30)),
        }
        tick['estado'] = estado
        tick['inicio_estado'] = time.time()
        tick['duracion'] = dur_map.get(estado, 30.0)
        logger.info(f'[SEM] Tick sincronizado sem {semaforo_id}: estado={estado} dur={tick["duracion"]}s')

    from app.database import supabase_post
    from datetime import datetime
    try:
        await supabase_post('ciclos', {
            'semaforo_id': semaforo_id,
            'estado': estado,
            'fecha': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.warning(f'[SEM] Error registro ciclo: {e}')

    return result[0] if result else {}


async def actualizar_tiempos(semaforo_id: int, tiempo_verde: int, tiempo_amarillo: int, tiempo_rojo: int) -> Dict:
    result = await supabase_patch('semaforos', {'id': semaforo_id}, {
        'tiempo_verde': tiempo_verde,
        'tiempo_amarillo': tiempo_amarillo,
        'tiempo_rojo': tiempo_rojo
    })
    return result[0] if result else {}


async def activar_semaforo(semaforo_id: int) -> Dict:
    result = await supabase_patch('semaforos', {'id': semaforo_id}, {'activo': True})
    return result[0] if result else {}


async def desactivar_semaforo(semaforo_id: int) -> Dict:
    result = await supabase_patch('semaforos', {'id': semaforo_id}, {'activo': False})
    return result[0] if result else {}


async def obtener_intersecciones() -> List[Dict]:
    """Devuelve todas las intersecciones de todos los mapas (aplanado desde la API de mapas)."""
    mapas = await _get_mapas_cached()
    intersecciones = []
    for mapa in mapas:
        clave = mapa['clave']
        for idx, inter in enumerate(mapa.get('config', {}).get('intersecciones', [])):
            intersecciones.append({
                'interseccion_id': _gen_int_id(clave, inter['pos'], idx),
                'mapa_clave': clave,
                'nombre': inter.get('nombre', f'Int {idx+1}').replace('\n', ' '),
                'pos_x': inter['pos'][0],
                'pos_y': inter['pos'][1],
                'mapa_nombre': mapa.get('nombre', clave),
                'tiene_semaforos': False  # se completa abajo si es necesario
            })
    return intersecciones


async def crear_semaforo(data: dict) -> Dict:
    """Crea un semáforo manualmente. data debe incluir mapa_clave, interseccion_id, direccion, etc."""
    result = await supabase_post('semaforos', data)
    invalidate_mapas_cache()
    return result[0] if result else {}


async def eliminar_semaforo(semaforo_id: int) -> bool:
    try:
        await supabase_delete('semaforos', {'id': semaforo_id})
        invalidate_mapas_cache()
        return True
    except Exception as e:
        logger.error(f'[SEM] Error eliminando sem {semaforo_id}: {e}')
        return False


async def eliminar_semaforos(ids: List[int]) -> int:
    if not ids:
        return 0
    try:
        await supabase_delete_bulk('semaforos', ids)
        invalidate_mapas_cache()
        return len(ids)
    except Exception as e:
        logger.error(f'[SEM] Error eliminando batch: {e}')
        return 0


async def eliminar_semaforos_por_mapa(mapa_clave: str) -> int:
    try:
        existentes = await supabase_get('semaforos', {'mapa_clave': f'eq.{mapa_clave}', 'select': 'id'})
        ids = [s['id'] for s in existentes]
        if ids:
            await supabase_delete_bulk('semaforos', ids)
        invalidate_mapas_cache()
        return len(ids)
    except Exception as e:
        logger.error(f'[SEM] Error eliminando por mapa {mapa_clave}: {e}')
        return 0


async def eliminar_todos_semaforos() -> int:
    try:
        existentes = await supabase_get('semaforos', {'select': 'id'})
        ids = [s['id'] for s in existentes]
        if ids:
            await supabase_delete_bulk('semaforos', ids)
        invalidate_mapas_cache()
        return len(ids)
    except Exception as e:
        logger.error(f'[SEM] Error eliminando todos: {e}')
        return 0


async def obtener_dashboard() -> Dict:
    mapas_raw = await _get_mapas_cached()
    semaforos = await supabase_get('semaforos', {'select': '*', 'order': 'mapa_clave.asc'})

    s_activos = sum(1 for s in semaforos if s.get('activo'))
    s_verde = sum(1 for s in semaforos if s.get('estado') == 'verde')
    s_amarillo = sum(1 for s in semaforos if s.get('estado') == 'amarillo')
    s_rojo = sum(1 for s in semaforos if s.get('estado') == 'rojo')
    total_inter = sum(len(m.get('config', {}).get('intersecciones', [])) for m in mapas_raw)

    mapas_info = []
    for mapa in mapas_raw:
        clave = mapa['clave']
        intersecciones_raw = mapa.get('config', {}).get('intersecciones', [])
        sems_mapa = [s for s in semaforos if s['mapa_clave'] == clave]

        intersecciones_info = []
        for idx, inter in enumerate(intersecciones_raw):
            int_id = _gen_int_id(clave, inter['pos'], idx)
            sems_inter = [s for s in sems_mapa if s['interseccion_id'] == int_id]
            intersecciones_info.append({
                'interseccion_id': int_id,
                'nombre': inter.get('nombre', '').replace('\n', ' '),
                'pos_x': inter['pos'][0],
                'pos_y': inter['pos'][1],
                'semaforos': sems_inter
            })

        mapas_info.append({
            'clave': clave,
            'nombre': mapa['nombre'],
            'color_tema': mapa.get('color_tema', '#00F0FF'),
            'width': mapa.get('width', 800),
            'height': mapa.get('height', 800),
            'total_intersecciones': len(intersecciones_raw),
            'total_semaforos': len(sems_mapa),
            'intersecciones': intersecciones_info,
            'config': mapa.get('config', {})
        })

    historial = []
    try:
        historial = await supabase_get('ciclos', {
            'select': '*',
            'order': 'fecha.desc',
            'limit': '50'
        })
    except Exception:
        pass

    from app.services.ciclo import get_ticks
    ticks = get_ticks()

    from app.services.ciclo import esta_activo

    return {
        'stats': {
            'total_mapas': len(mapas_raw),
            'total_intersecciones': total_inter,
            'total_semaforos': len(semaforos),
            'semaforos_activos': s_activos,
            'semaforos_verde': s_verde,
            'semaforos_amarillo': s_amarillo,
            'semaforos_rojo': s_rojo,
            'ciclo_activo': esta_activo()
        },
        'mapas': mapas_info,
        'semaforos': semaforos,
        'historial': historial,
        'tick_counters': {str(k): v for k, v in ticks.items()}
    }
