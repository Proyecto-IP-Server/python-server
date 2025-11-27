from contextlib import asynccontextmanager
from fastapi import  FastAPI
import asyncio
import httpx
import json
import os
from database import create_db_and_tables
from scraper_service import scrape_and_update_db


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
ALIAS_CENTROS_PATH = os.path.join(
    os.path.dirname(__file__), "alias_centros.json")
alias_a_centro = {}
centro_a_alias = {}
with open(ALIAS_CENTROS_PATH, 'r', encoding='utf-8') as f:
    for nombre, alias in json.load(f).items():
        if nombre and alias:
            alias_a_centro[alias] = nombre
            centro_a_alias[nombre] = alias

# --- Tareas de Fondo ---


async def background_scraper_loop(lock: asyncio.Lock, client: httpx.AsyncClient):
    while True:
        await asyncio.sleep(600)  # Cada 10 minutos
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
