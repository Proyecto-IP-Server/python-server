import asyncio
import httpx
from typing import Annotated
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlmodel import select, Session

# Importar dependencias, modelos y el servicio de scrapeo
from database import SessionDep, create_db_and_tables
from models import *
from scraper_service import scrape_and_update_db, scrape_and_update_targeted

# --- Dependencias de Endpoints ---

def validar_ciclo(ciclo: str, session: SessionDep) -> int:
    id_ciclo = session.exec(select(Ciclo.id).where(
        Ciclo.nombre == ciclo)).first()
    if id_ciclo is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    return id_ciclo


def validar_materia(materia: str, session: SessionDep) -> int:
    id_materia = session.exec(select(Materia.id).where(
        Materia.clave == materia)).first()
    if id_materia is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return id_materia

def validar_centro(centro: str, session: SessionDep) -> int:
    id_centro = session.exec(select(Centro.id).where(
        Centro.nombre == centro)).first()
    if id_centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    return id_centro


CicloDep = Annotated[int, Depends(validar_ciclo)]
MateriaDep = Annotated[int, Depends(validar_materia)]
CentroDep = Annotated[int, Depends(validar_centro)]

# --- Tareas de Fondo ---

async def background_scraper_loop(lock: asyncio.Lock, client: httpx.AsyncClient):
    """
    Loop infinito que ejecuta el scrapeo cada 5 minutos.
    """
    while True:
        await asyncio.sleep(300) # 300 segundos = 5 minutos
        print("\n--- [TAREA DE FONDO] Iniciando scrapeo programado ---")
        await scrape_and_update_db(lock, client)


# --- Configuración y Ciclo de Vida de FastAPI ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear objetos de estado
    app.state.scrape_lock = asyncio.Lock()
    app.state.http_client = httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36"
        }
    )
    
    # Crear tablas
    print("Creando tablas de la base de datos...")
    create_db_and_tables()
    
    # Ejecutar el primer scrapeo al inicio
    print("Ejecutando scrapeo inicial en segundo plano...")
    asyncio.create_task(scrape_and_update_db(
        app.state.scrape_lock, 
        app.state.http_client
    ))
    print("El scrapeo inicial esta corriendo. La aplicacion esta lista.")
    # Iniciar la tarea de fondo
    asyncio.create_task(background_scraper_loop(
        app.state.scrape_lock, 
        app.state.http_client
    ))

    yield
    
    # Limpiar al cerrar
    print("Cerrando cliente HTTP...")
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)

# --- Endpoints ---

@app.get("/materias/", response_model=list[MateriaPublic])
def read_materias(
        session: SessionDep,
        carrera: str | None = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):

    stmt = select(Materia)
    if carrera is not None:
        stmt = stmt.join(Carrera).where(Carrera.nombre == carrera)

    materias = session.exec(stmt.offset(offset).limit(limit)).all()

    result: list[MateriaPublic] = []
    for m in materias:
        result.append(MateriaPublic(
            clave=m.clave,
            nombre=m.nombre,
            carrera=m.carrera.nombre
        ))
    return result


@app.get("/materia/{materia}/{ciclo}/secciones", response_model=list[SeccionPublic])
def read_secciones_de_materia(session: SessionDep, materia: MateriaDep, ciclo: CicloDep):
    secciones = session.exec(select(Seccion).where(
        Seccion.id_materia == materia, Seccion.id_ciclo == ciclo)).all()
    secciones_public: list[SeccionPublic] = []
    for s in secciones or []:
        sesiones_public: list[SesionPublic] = []
        for ses in s.sesiones or []:
            sesiones_public.append(SesionPublic(
                salon=ses.aula.salon,
                edificio=ses.aula.edificio,
                fecha_inicio=ses.fecha_inicio,
                fecha_fin=ses.fecha_fin,
                hora_inicio=ses.hora_inicio,
                hora_fin=ses.hora_fin,
                dia_semana=ses.dia_semana
            ))

        secciones_public.append(SeccionPublic(
            numero=s.numero,
            nrc=s.nrc,
            profesor=s.profesor.nombre,
            centro=s.centro.nombre,
            sesiones=sesiones_public,
            cupos=s.cupos,
            disponibilidad=s.disponibilidad
        ))
    return secciones_public


@app.get("/materia/{materia}", response_model=MateriaPublic)
def read_materia(session: SessionDep, materia: MateriaDep):
    m = session.get(Materia, materia)
    if not m:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return MateriaPublic(
                clave=m.clave,
                nombre=m.nombre,
                carrera=m.carrera.nombre
            )

@app.get("/resenas/", response_model=list[ResenaPublic])
def read_resenas(
        session: SessionDep,
        profesor: str | None = None,
        materia: str | None = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):
    
    # (Lógica original incompleta)
    return []


@app.get("/ciclos/", response_model=list[str])
def read_ciclos(session: SessionDep):
    ciclos = session.exec(select(Ciclo)).all()
    return [c.nombre for c in ciclos]

@app.get("/centros/", response_model=list[str])
def read_centros(session: SessionDep):
    centros = session.exec(select(Centro)).all()
    return [c.nombre for c in centros]

@app.get("/carreras/{ciclo}/{centro}", response_model=list[str])
def read_carreras(session: SessionDep, ciclo: CicloDep, centro: CentroDep):
    statement = (
        select(Carrera.nombre)
        .join(Materia)  
        .join(Seccion)
        .join(Centro)
        .join(Ciclo)
        .where(Centro.id == centro)
        .where(Ciclo.id == ciclo)
        .distinct()
        )
    
    carreras = session.exec(statement).all()
    return carreras

# --- Endpoints ---

@app.post("/admin/refresh")
async def trigger_refresh(request: Request):
    """
    Endpoint para forzar una actualización de la base de datos.
    """
    lock = request.app.state.scrape_lock
    client = request.app.state.http_client

    if lock.locked():
        raise HTTPException(status_code=429, detail="Un scrapeo ya está en curso.")
    
    # Inicia la tarea en segundo plano y responde inmediatamente
    asyncio.create_task(scrape_and_update_db(lock, client))
    return {"message": "Proceso de actualización iniciado en segundo plano."}



