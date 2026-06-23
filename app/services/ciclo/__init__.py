import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, List, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)

_TICK_COUNTERS: Dict[int, Dict] = {}
_CICLO_TASK: Optional[asyncio.Task] = None
_CICLO_RUNNING: bool = False
_SEMAFOROS_CACHE: List[dict] = []
_DB_SEMAPHORE = asyncio.Semaphore(10)

GRUPOS = {
    'NS': ['NS', 'SN'],
    'EO': ['EO', 'OE'],
}


def duracion_estado(sem: dict, estado: str) -> float:
    mapa = {
        'verde': float(sem.get('tiempo_verde', 30)),
        'amarillo': float(sem.get('tiempo_amarillo', 5)),
        'rojo': float(sem.get('tiempo_rojo', 30)),
    }
    return mapa.get(estado, 30.0)


def get_grupo(direccion: str) -> str:
    for grupo, dirs in GRUPOS.items():
        if direccion in dirs:
            return grupo
    return 'NS'


class CicloPersistencia:
    """Cola asíncrona para desacoplar escrituras a Supabase del ciclo."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None

    async def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._worker())

    async def stop(self):
        if self.task and not self.task.done():
            await self.queue.put(None)
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def enqueue(self, item: dict):
        await self.queue.put(item)

    async def _worker(self):
        logger.info('[PERSIST] Worker iniciado')
        while True:
            item = await self.queue.get()
            if item is None:
                break
            try:
                async with _DB_SEMAPHORE:
                    await asyncio.gather(
                        _supabase_patch('semaforos', {'id': item['id']}, {'estado': item['estado_nuevo']}),
                        _supabase_post('ciclos', {
                            'semaforo_id': item['id'],
                            'estado': item['estado_nuevo'],
                            'fecha': item['fecha']
                        }),
                        return_exceptions=True
                    )
            except Exception as e:
                logger.error(f'[PERSIST] Error sem {item.get("id")}: {e}')
        logger.info('[PERSIST] Worker detenido')


_PERSISTENCIA = CicloPersistencia()


# Referencias locales a funciones de database para evitar import circular
_supabase_patch = None
_supabase_post = None


def _set_db_funcs(patch_fn, post_fn):
    global _supabase_patch, _supabase_post
    _supabase_patch = patch_fn
    _supabase_post = post_fn


class IntersectionController:
    """
    Máquina de estados por intersección.

    Fases:
      0. NS verde   -> NS = verde, EO = rojo
      1. NS amarillo-> NS = amarillo, EO = rojo
      2. All-red    -> NS = rojo, EO = rojo  (clearance)
      3. EO verde   -> NS = rojo, EO = verde
      4. EO amarillo-> NS = rojo, EO = amarillo
      5. All-red    -> NS = rojo, EO = rojo  (clearance)
    """

    FASES = [
        ('NS', 'verde'),
        ('NS', 'amarillo'),
        (None, 'rojo'),   # all-red
        ('EO', 'verde'),
        ('EO', 'amarillo'),
        (None, 'rojo'),   # all-red
    ]

    def __init__(self, interseccion_id: str, semaforos: List[dict]):
        self.interseccion_id = interseccion_id
        self.semaforos_por_grupo = {'NS': [], 'EO': []}
        for sem in semaforos:
            grupo = get_grupo(sem['direccion'])
            self.semaforos_por_grupo[grupo].append(sem)

        self.fase_idx = 0
        self.inicio_fase = time.time()
        self.duracion_fase = self._duracion_fase()
        self._init_ticks()
        logger.info(f'[IC] Creado {interseccion_id}: fase={self.FASES[0]} dur={self.duracion_fase}s')

    def _sem_referencia(self, grupo: str):
        sems = self.semaforos_por_grupo.get(grupo, [])
        return sems[0] if sems else None

    def _duracion_fase(self) -> float:
        grupo_activo, estado = self.FASES[self.fase_idx]
        if grupo_activo:
            sem = self._sem_referencia(grupo_activo)
            return duracion_estado(sem, estado) if sem else 30.0
        sem = self._sem_referencia('NS') or self._sem_referencia('EO')
        return duracion_estado(sem, 'rojo') if sem else 30.0

    def _init_ticks(self):
        ahora = time.time()
        grupo_activo, estado_activo = self.FASES[self.fase_idx]
        for grupo, sems in self.semaforos_por_grupo.items():
            for sem in sems:
                sid = sem['id']
                if grupo_activo and grupo == grupo_activo:
                    estado = estado_activo
                else:
                    estado = 'rojo'
                _TICK_COUNTERS[sid] = {
                    'estado': estado,
                    'inicio_estado': ahora,
                    'duracion': self.duracion_fase,
                    'direccion': sem['direccion'],
                    'interseccion_id': self.interseccion_id,
                    'grupo': grupo,
                    'sem': sem
                }

    def tick(self, ahora: float) -> List[dict]:
        elapsed = ahora - self.inicio_fase
        if elapsed < self.duracion_fase:
            return []

        self.fase_idx = (self.fase_idx + 1) % len(self.FASES)
        self.inicio_fase = ahora
        self.duracion_fase = self._duracion_fase()
        grupo_activo, estado_activo = self.FASES[self.fase_idx]

        cambios = []
        for grupo, sems in self.semaforos_por_grupo.items():
            for sem in sems:
                sid = sem['id']
                tick = _TICK_COUNTERS.get(sid, {})
                estado_anterior = tick.get('estado', 'rojo')

                if grupo_activo and grupo == grupo_activo:
                    estado_nuevo = estado_activo
                else:
                    estado_nuevo = 'rojo'

                tick.update({
                    'estado': estado_nuevo,
                    'inicio_estado': ahora,
                    'duracion': self.duracion_fase,
                    'direccion': sem['direccion'],
                    'interseccion_id': self.interseccion_id,
                    'grupo': grupo,
                    'sem': sem
                })
                _TICK_COUNTERS[sid] = tick

                if estado_anterior != estado_nuevo:
                    cambios.append({
                        'id': sid,
                        'dir': sem['direccion'],
                        'grupo': grupo,
                        'estado_anterior': estado_anterior,
                        'estado_nuevo': estado_nuevo,
                        'duracion': self.duracion_fase,
                        'sem': sem
                    })
                    logger.info(f'[IC] {self.interseccion_id}: sem {sid} {estado_anterior} -> {estado_nuevo}')

        return cambios


_INTERSECTION_CTRLS: Dict[str, 'IntersectionController'] = {}


def _build_controllers(semaforos: List[dict]):
    global _INTERSECTION_CTRLS, _SEMAFOROS_CACHE
    por_int = defaultdict(list)
    for sem in semaforos:
        por_int[sem['interseccion_id']].append(sem)

    _INTERSECTION_CTRLS.clear()
    for int_id, sems in por_int.items():
        ctrl = IntersectionController(int_id, sems)
        _INTERSECTION_CTRLS[int_id] = ctrl

    logger.info(f'[CI] {len(_INTERSECTION_CTRLS)} controladores creados')


async def iniciar_ciclo(broadcast_fn: Optional[Callable] = None) -> Dict:
    global _CICLO_TASK, _CICLO_RUNNING, _TICK_COUNTERS, _INTERSECTION_CTRLS, _SEMAFOROS_CACHE
    logger.info(f'[CI] iniciar_ciclo, running={_CICLO_RUNNING}')

    if _CICLO_RUNNING:
        return {'mensaje': 'Ciclo ya esta corriendo'}

    _CICLO_RUNNING = True
    _TICK_COUNTERS = {}
    _INTERSECTION_CTRLS.clear()
    _SEMAFOROS_CACHE = []

    from app.database import supabase_patch, supabase_post
    _set_db_funcs(supabase_patch, supabase_post)
    await _PERSISTENCIA.start()

    async def ciclo_loop():
        global _CICLO_RUNNING, _TICK_COUNTERS, _SEMAFOROS_CACHE
        logger.info('[CI] ===== CICLO INICIADO =====')

        from app.database import supabase_get

        while _CICLO_RUNNING:
            t0 = time.perf_counter()
            try:
                ahora = time.time()

                if not _INTERSECTION_CTRLS:
                    logger.info('[CI] Fetching semaforos...')
                    _SEMAFOROS_CACHE = await supabase_get('semaforos', {
                        'activo': 'eq.true',
                        'modo': 'eq.automatico',
                        'select': '*'
                    })
                    logger.info(f'[CI] Recibidos {len(_SEMAFOROS_CACHE)} semaforos')
                    _build_controllers(_SEMAFOROS_CACHE)

                cambios_a_procesar = []
                for int_id, ctrl in _INTERSECTION_CTRLS.items():
                    cambios = ctrl.tick(ahora)
                    cambios_a_procesar.extend(cambios)

                # Encolar escrituras a DB (no bloquean el ciclo)
                if cambios_a_procesar:
                    ts = datetime.utcnow().isoformat()
                    for c in cambios_a_procesar:
                        await _PERSISTENCIA.enqueue({
                            'id': c['id'],
                            'estado_nuevo': c['estado_nuevo'],
                            'fecha': ts
                        })

                # Broadcast: delta cuando hay cambios, full state periódicamente
                if broadcast_fn and _TICK_COUNTERS:
                    estado_live = []
                    for sid, tick in _TICK_COUNTERS.items():
                        elapsed = ahora - tick['inicio_estado']
                        remaining = max(0, tick['duracion'] - elapsed)
                        sem = next((s for s in _SEMAFOROS_CACHE if s['id'] == sid), None)
                        if sem:
                            estado_live.append({
                                'id': sid,
                                'mapa_clave': sem['mapa_clave'],
                                'interseccion_id': tick['interseccion_id'],
                                'direccion': tick['direccion'],
                                'estado': tick['estado'],
                                'segundos_restantes': round(remaining, 1),
                                'duracion_total': tick['duracion'],
                                'grupo': tick['grupo']
                            })

                    try:
                        if cambios_a_procesar:
                            await broadcast_fn({
                                'tipo': 'actualizacion_ciclo',
                                'timestamp': datetime.utcnow().isoformat(),
                                'semaforos': [
                                    {
                                        'id': c['id'],
                                        'estado': c['estado_nuevo'],
                                        'estado_anterior': c['estado_anterior'],
                                        'duracion': c['duracion']
                                    }
                                    for c in cambios_a_procesar
                                ]
                            })
                        else:
                            await broadcast_fn({
                                'tipo': 'estado_live',
                                'timestamp': datetime.utcnow().isoformat(),
                                'semaforos': estado_live
                            })
                    except Exception as e:
                        logger.error(f'[CI] Broadcast error: {e}')

                elapsed_loop = time.perf_counter() - t0
                if elapsed_loop > 0.05:
                    logger.warning(f'[PERF] ciclo tick tomó {elapsed_loop*1000:.1f}ms')

                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                logger.info('[CI] Cancelled')
                break
            except Exception as e:
                logger.error(f'[CI] Error: {e}')
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)

        logger.info('[CI] ===== CICLO DETENIDO =====')

    _CICLO_TASK = asyncio.create_task(ciclo_loop())
    return {'mensaje': 'Ciclo automatico iniciado'}


async def detener_ciclo(broadcast_fn: Optional[Callable] = None) -> Dict:
    global _CICLO_TASK, _CICLO_RUNNING, _TICK_COUNTERS, _INTERSECTION_CTRLS
    logger.info(f'[CI] detener_ciclo, running={_CICLO_RUNNING}')

    _CICLO_RUNNING = False
    _TICK_COUNTERS = {}
    _INTERSECTION_CTRLS.clear()

    if _CICLO_TASK:
        _CICLO_TASK.cancel()
        _CICLO_TASK = None

    await _PERSISTENCIA.stop()

    if broadcast_fn:
        await broadcast_fn({'tipo': 'ciclo_detenido'})

    return {'mensaje': 'Ciclo automatico detenido'}


def esta_activo() -> bool:
    return _CICLO_RUNNING


def get_ticks() -> Dict:
    return _TICK_COUNTERS.copy()
