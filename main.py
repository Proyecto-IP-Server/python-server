import asyncio
import httpx
import random
import datetime
from typing import Annotated

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select, Session, and_
from pydantic import BaseModel, Field

# Importar dependencias, modelos y el servicio de scrapeo
from database import SessionDep
from models import *
from scraper_service import scrape_and_update_db, scrape_specific_materia
from email_service import enviar_reporte_soporte
from routes import *
from dependencies import *
from lifespan import app





@app.post("/admin/refresh", response_model=RefreshResponse)
async def trigger_refresh(datos: RefreshRequest, request: Request, session: SessionDep):
    """
    Endpoint para refrescar una materia específica.
    Inicia un worker asíncrono independiente del scraping principal.

    El usuario proporciona el nombre o alias del centro, el sistema lo resuelve internamente.
    """
    client = request.app.state.http_client

    # Obtener la clave (cup) del centro desde la BD
    centro_clave, centro_nombre_real = obtener_clave_centro(
        datos.centro, session)

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
        raise HTTPException(
            status_code=429, detail="Un scrapeo ya está en curso.")

    # Inicia la tarea en segundo plano y responde inmediatamente
    asyncio.create_task(scrape_and_update_db(
        lock, client, num_ciclos_recientes=1, inicial=False))
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
        raise HTTPException(
            status_code=500, detail="Error interno al enviar el reporte")
