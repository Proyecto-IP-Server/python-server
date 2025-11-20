import asyncio
import httpx
import random
import datetime
from typing import Annotated
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select, Session, and_
from pydantic import BaseModel, Field
import json
import os

# Importar dependencias, modelos y el servicio de scrapeo
from database import SessionDep, create_db_and_tables
from models import *
from scraper_service import scrape_and_update_db, scrape_specific_materia
from email_service import enviar_enlace_verificacion, enviar_reporte_soporte
import hashlib

# --- Configuración de Actualización Histórica ---
HISTORICAL_UPDATE_INTERVAL_HOURS = 24  

async def daily_historical_update_loop(lock: asyncio.Lock, client: httpx.AsyncClient):
    while True:

        await asyncio.sleep(HISTORICAL_UPDATE_INTERVAL_HOURS * 60 * 60)
        
        print(f"\n{'='*60}")
        print(f"[ACTUALIZACIÓN HISTÓRICA] Iniciando scrapeo de ciclos históricos...")
        print(f"  Intervalo: cada {HISTORICAL_UPDATE_INTERVAL_HOURS} horas")
        print(f"{'='*60}")
        
        try:
            await scrape_and_update_db(
                lock=lock,
                client=client,
                num_ciclos_recientes=1,
                inicial=False,
                force_historical=True
            )
            print(f"\n[ACTUALIZACIÓN HISTÓRICA] Completado exitosamente.")
        except Exception as e:
            print(f"\n[ACTUALIZACIÓN HISTÓRICA] Error: {e}")
            import traceback
            traceback.print_exc()

# Cargar alias de centros
ALIAS_CENTROS_PATH = os.path.join(os.path.dirname(__file__), "alias_centros.json")
with open(ALIAS_CENTROS_PATH, 'r', encoding='utf-8') as f:
    ALIAS_CENTROS = json.load(f)

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

        nombre_original = None
        for nombre, alias in ALIAS_CENTROS.items():
            if alias == centro:
                nombre_original = nombre
                break
        
        if nombre_original:
            id_centro = session.exec(select(Centro.id).where(
                Centro.nombre == nombre_original)).first()
    
    if id_centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    return id_centro

def centro_opcional(session: SessionDep, centro: str | None = None) -> int | None:
    if centro is None:
        return None
    return validar_centro(centro, session)

def obtener_clave_centro(centro_nombre: str, session: SessionDep) -> tuple[str, str]:

    centro = session.exec(select(Centro).where(Centro.nombre == centro_nombre)).first()
    
    if centro is None:

        nombre_original = None
        for nombre, alias in ALIAS_CENTROS.items():
            if alias == centro_nombre:
                nombre_original = nombre
                break
        
        if nombre_original:
            centro = session.exec(select(Centro).where(Centro.nombre == nombre_original)).first()
    
    if centro is None:
        raise HTTPException(
            status_code=404, 
            detail=f"Centro '{centro_nombre}' no encontrado. Debe ejecutarse el scraping principal primero."
        )
    
    if centro.clave is None:
        raise HTTPException(
            status_code=400, 
            detail=f"Centro '{centro.nombre}' no tiene clave asignada. Se asignará en el próximo scraping automático."
        )
    
    return centro.clave, centro.nombre

def validar_alumno(correo_alumno: str, session: SessionDep) -> int:
    if not correo_alumno.endswith("@alumnos.udg.mx"):
        raise HTTPException(
            status_code=400, 
            detail="No es un correo válido de alumno (@alumnos.udg.mx)"
        )
    
    alumno = session.exec(select(Alumno)
                        .where(Alumno.correo == correo_alumno)).first()
    if alumno is None:
        # Crear alumno si no existe
        alumno = Alumno(correo=correo_alumno)
        session.add(alumno)
        session.commit()
        session.refresh(alumno)
    
    if alumno.id is None:
        raise HTTPException(status_code=500, detail="Error" )
    
    return alumno.id

def validar_profesor(nombre_profesor: str, session: SessionDep) -> int:
    id_profesor = session.exec(select(Profesor.id).where(
        Profesor.nombre == nombre_profesor)).first()
    if id_profesor is None:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")
    return id_profesor

def validar_carrera(carrera: str, session: SessionDep) -> int:
    id_carrera = session.exec(select(Carrera.id).where(
        Carrera.clave == carrera)).first()
    if id_carrera is None:
        raise HTTPException(status_code=404, detail="Carrera no encontrada")
    return id_carrera

def carrera_opcional(session: SessionDep, carrera: str | None = None) -> int | None:
    if carrera is None:
        return None
    return validar_carrera(carrera, session)

CicloDep = Annotated[int, Depends(validar_ciclo)]
MateriaDep = Annotated[int, Depends(validar_materia)]
CentroDep = Annotated[int, Depends(validar_centro)]
AlumnoDep = Annotated[int, Depends(validar_alumno)]
ProfesorDep = Annotated[int, Depends(validar_profesor)]
CarreraDep = Annotated[int, Depends(validar_carrera)]
CentroOptDep = Annotated[int | None, Depends(centro_opcional)]
CarreraOptDep = Annotated[int | None, Depends(carrera_opcional)]
# --- Tareas de Fondo ---

async def background_scraper_loop(lock: asyncio.Lock, client: httpx.AsyncClient):
    while True:
        await asyncio.sleep(3600) # 300 segundos = 5 minutos
        print("\n--- [TAREA DE FONDO] Iniciando scrapeo programado ---")
        await scrape_and_update_db(lock, client, num_ciclos_recientes=1, inicial=False)


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
    
    # Ejecutar el primer scrapeo al inicio (con procesamiento de ciclos históricos)
    print("Ejecutando scrapeo inicial en segundo plano...")
    print("  -> Se scrapeara 1 ciclo reciente")
    print("  -> Se scrapearan hasta 10 ciclos históricos que NO tengan datos")
    asyncio.create_task(scrape_and_update_db(
        app.state.scrape_lock, 
        app.state.http_client,
        num_ciclos_recientes=1,
        inicial=True  # Esto habilita el scrapeo de ciclos históricos sin datos
    ))
    print("El scrapeo inicial esta corriendo. La aplicacion esta lista.")
    
    # Iniciar la tarea de fondo (solo ciclos recientes)
    asyncio.create_task(background_scraper_loop(
        app.state.scrape_lock, 
        app.state.http_client
    ))

    # Iniciar loop diario para actualización histórica condicional
    asyncio.create_task(daily_historical_update_loop(
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
        ciclo: CicloDep,
        carrera: CarreraOptDep = None,
        centro: CentroOptDep = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=1000)] = 1000):

    stmt = select(Materia).join(Seccion).where(
        Seccion.id_ciclo == ciclo
    )
    
    if carrera is not None:
        stmt = stmt.join(CarreraMateriaLink,  
                        and_(CarreraMateriaLink.id_carrera == carrera, 
                            CarreraMateriaLink.id_materia == Materia.id))

    if centro is not None:
        stmt = stmt.where(Seccion.id_centro == centro)

    materias = session.exec(stmt.distinct().offset(offset).limit(limit)).all()

    result: list[MateriaPublic] = []
    for m in materias:
        result.append(MateriaPublic(
            clave=m.clave,
            nombre=m.nombre,
            creditos=m.creditos
        ))
    return result


@app.get("/materia/{centro}/{materia}/{ciclo}/secciones", response_model=list[SeccionPublic])
def read_secciones_de_materia(session: SessionDep, centro: CentroDep, materia: MateriaDep, ciclo: CicloDep):
    secciones = session.exec(select(Seccion).where(
        Seccion.id_materia == materia, 
        Seccion.id_ciclo == ciclo,
        Seccion.id_centro == centro)).all()
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
                creditos=m.creditos
            )

@app.get("/ciclos/", response_model=list[str])
def read_ciclos(session: SessionDep):
    ciclos = session.exec(select(Ciclo)).all()
    return sorted([c.nombre for c in ciclos], reverse=True)

@app.get("/centros/", response_model=list[str])
def read_centros(session: SessionDep):
    centros = session.exec(select(Centro)).all()
    result = []
    for c in centros:
        alias = ALIAS_CENTROS.get(c.nombre, "")

        centro_display = alias if alias else c.nombre
        result.append(centro_display)
    return sorted(result)

@app.get("/carreras/{ciclo}/{centro}", response_model=list[CarreraPublic])
def read_carreras(session: SessionDep, ciclo: CicloDep, centro: CentroDep):

    statement = (
        select(Carrera)
        .select_from(Carrera)
        .join(CentroCarreraLink, CentroCarreraLink.id_carrera == Carrera.id) # type: ignore
        .join(CarreraMateriaLink, CarreraMateriaLink.id_carrera == Carrera.id) # type: ignore
        .join(Seccion, and_(
            Seccion.id_materia == CarreraMateriaLink.id_materia,
            Seccion.id_centro == centro,
            Seccion.id_ciclo == ciclo
        ))
        .where(CentroCarreraLink.id_centro == centro)
        .distinct()
        )
    carreras = session.exec(statement).all()
    return [CarreraPublic(clave=c.clave, nombre=c.nombre) for c in carreras]

# Reseñas
@app.get("/resenas/", response_model=list[ResenaPublic])
def read_resenas(
        session: SessionDep,
        profesor: str | None = None,
        materia: str | None = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):
    
    stmt = select(Resena)
    
    if profesor is not None:
        id_profesor = session.exec(select(Profesor.id).where(
            Profesor.nombre == profesor)).first()
        if id_profesor is None:
            raise HTTPException(status_code=404, detail="Profesor no encontrado")
        stmt = stmt.where(Resena.id_profesor == id_profesor)
    
    if materia is not None:
        id_materia = session.exec(select(Materia.id).where(
            Materia.clave == materia)).first()
        if id_materia is None:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
        stmt = stmt.where(Resena.id_materia == id_materia)
    
    resenas = session.exec(stmt.offset(offset).limit(limit)).all()
    
    result: list[ResenaPublic] = []
    for r in resenas:
        result.append(ResenaPublic(
            profesor=r.profesor.nombre,
            materia=r.materia.clave,
            alumno=hashlib.sha256(r.alumno.correo.encode('utf-8')).hexdigest(),
            contenido=r.contenido,
            satisfaccion=r.satisfaccion
        ))
    return result

@app.post("/resenas/solicitar", response_model=ResenaPendienteResponse)
async def solicitar_resena(
    datos: ResenaPendienteCreate, 
    session: SessionDep, 
    request: Request
):

    id_alumno = validar_alumno(datos.correo_alumno, session)
    id_materia = validar_materia(datos.clave_materia, session)
    id_profesor = validar_profesor(datos.nombre_profesor, session)
    

    resena_existente = session.exec(
        select(Resena).where(
            Resena.id_profesor == id_profesor,
            Resena.id_materia == id_materia,
            Resena.id_alumno == id_alumno
        )
    ).first()
    
    if resena_existente:
        raise HTTPException(
            status_code=409, 
            detail="Reseña ya existe (editar???)" #TAG: Agregar editar reseña?
        )
    
    # Verificar si ya existe una reseña pendiente
    pendiente_existente = session.exec(
        select(ResenaPendiente).where(
            ResenaPendiente.id_profesor == id_profesor,
            ResenaPendiente.id_materia == id_materia,
            ResenaPendiente.id_alumno == id_alumno
        )
    ).first()
    # Generar un código único de 6 dígitos, valida en la db si ya existe, si ya crea uno nuevo
    while True:
        codigo = str(random.randint(0, 999999)).zfill(6)

        codigo_existente = session.exec(
            select(ResenaPendiente).where(ResenaPendiente.codigo == codigo)
            ).first()
        if not codigo_existente:
            break

    if pendiente_existente:

        pendiente_existente.contenido = datos.contenido
        pendiente_existente.satisfaccion = datos.satisfaccion
        pendiente_existente.codigo = codigo
        pendiente_existente.fecha_creacion = datetime.datetime.utcnow()
        session.commit()
    else:

        nueva_pendiente = ResenaPendiente(
            id_profesor=id_profesor,
            id_materia=id_materia,
            id_alumno=id_alumno,
            contenido=datos.contenido,
            satisfaccion=datos.satisfaccion,
            codigo=codigo
        )
        print(f"DEBUG: profesor:{id_profesor}, materia:{id_materia}, alumno:{id_alumno}")
        print(f"DEBUG: Tipo de datos: {type(id_profesor)}, {type(id_materia)}, {type(id_alumno)}")
        session.add(nueva_pendiente)
        session.commit()
    
    
    try:

        base_url = "http://localhost:8080/api" or str(request.base_url).rstrip('/')+"/api" #TAG: Ajustar URL base para producción

        print(f"DEBUG: base_url para email: {base_url}")
        await enviar_enlace_verificacion(datos.correo_alumno, codigo, base_url)

    except Exception as e:
        
        return ResenaPendienteResponse(
            mensaje="Reseña guardada, pero hubo un error al enviar el correo de verificación",
            advertencia=f"Error: {str(e)}"
        )
    
    return ResenaPendienteResponse(
        mensaje=f"Reseña guardada. Revisa tu correo ({datos.correo_alumno}) para verificar y publicar."
    )


@app.get("/resenas/verificar/{codigo}", response_model=ResenaVerificadaResponse)
async def verificar_resena(
    codigo: str, 
    session: SessionDep,
    json: bool = Query(False)
):
    pendiente = session.exec(
        select(ResenaPendiente).where(ResenaPendiente.codigo == codigo)
    ).first()
    
    if not pendiente:
        if json:
            raise HTTPException(
                status_code=404,
                detail="El enlace de verificación no es válido o ya fue utilizado."
            )
        
        return HTMLResponse("""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h2 style="color: #dc2626;">Codigo inválido</h2>
                <p>El enlace de verificación no es válido o ya fue utilizado.</p>
            </body>
        </html>
        """)
    
    # Crear la reseña pública
    resena_publica = Resena(
        id_profesor=int(pendiente.id_profesor),
        id_materia=int(pendiente.id_materia),
        id_alumno=int(pendiente.id_alumno),
        contenido=pendiente.contenido,
        satisfaccion=pendiente.satisfaccion
    )
    
    try:
        session.add(resena_publica)
        session.delete(pendiente)
        session.commit()
        
        if json:
            return ResenaVerificadaResponse(
                mensaje="Reseña publicada exitosamente",
                status="success"
            )
        
        return HTMLResponse("""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h1 style="color: #16a34a;"> Reseña publicada.</h1>
                <p>Tu reseña ha sido verificada y ahora es pública.</p>
            </body>
        </html>
        """)
    except Exception as e:
        session.rollback()
        if json:
            raise HTTPException(
                status_code=500,
                detail=f"Error al publicar la reseña: {str(e)}"
            )
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h2 style="color: #dc2626;">Error</h2>
                <p>Error: {str(e)}</p>
            </body>
        </html>
        """)


@app.post("/admin/refresh", response_model=RefreshResponse)
async def trigger_refresh(datos: RefreshRequest, request: Request, session: SessionDep):
    """
    Endpoint para refrescar una materia específica.
    Inicia un worker asíncrono independiente del scraping principal.
    
    El usuario proporciona el nombre o alias del centro, el sistema lo resuelve internamente.
    """
    client = request.app.state.http_client
    
    # Obtener la clave (cup) del centro desde la BD
    centro_clave, centro_nombre_real = obtener_clave_centro(datos.centro, session)
    
    # Crear una tarea asíncrona independiente que NO usa el lock global
    async def refresh_task():
        try:
            resultado = await scrape_specific_materia(
                client=client,
                ciclo_nombre=datos.ciclo,
                centro_clave=centro_clave,
                carrera_codigo=datos.carrera,
                materia_clave=datos.materia
            )
            if resultado:
                print(f"Refresh completado exitosamente: {datos.materia}")
            else:
                print(f"Refresh falló: {datos.materia}")
        except Exception as e:
            print(f"Error en refresh task: {e}")
    
    # Iniciar la tarea en segundo plano
    asyncio.create_task(refresh_task())
    
    return RefreshResponse(
        mensaje="Proceso de actualización iniciado",
        status="processing",
        detalles={
            "ciclo": datos.ciclo,
            "centro": datos.centro,
            "carrera": datos.carrera,
            "materia": datos.materia
        }
    )

@app.post("/admin/refresh-full")
async def trigger_full_refresh(request: Request):
    """
    Endpoint para refrescar todos los ciclos recientes (scrapeo completo).
    """
    lock = request.app.state.scrape_lock
    client = request.app.state.http_client

    if lock.locked():
        raise HTTPException(status_code=429, detail="Un scrapeo ya está en curso.")
    
    # Inicia la tarea en segundo plano y responde inmediatamente
    asyncio.create_task(scrape_and_update_db(lock, client, num_ciclos_recientes=1, inicial=False))
    return {"message": "Proceso de actualización completa iniciado en segundo plano."}

@app.get("/abu")
async def abu_endpoint():
    with open("cadena.txt", "r", encoding="utf-8") as f:
        contenido = f.read()
    import base64
    contenido_bytes = contenido.encode('utf-8')
    contenido_decodificado = base64.b64decode(contenido_bytes).decode('utf-8')
    return HTMLResponse(content=contenido_decodificado, media_type="text/plain")

@app.post("/soporte")
async def recibir_soporte(datos: SoporteRequest):
    try:
        await enviar_reporte_soporte(datos)
        return {"mensaje": "Reporte enviado correctamente", "status": "success"}
    except Exception as e:
        print(f"Error en endpoint soporte: {e}")
        raise HTTPException(status_code=500, detail="Error interno al enviar el reporte")