import datetime
import asyncio
import httpx
import json
import os
from bs4 import BeautifulSoup
from sqlmodel import Session, select

# Importar el engine de la BD y los modelos
from database import engine
from models import *

# --- Constantes del Scraper ---
BASE_URL = 'http://consulta.siiau.udg.mx/wco/'
FORMA_CONSULTA_URL = f"{BASE_URL}sspseca.forma_consulta"
LISTA_CARRERAS_URL = f"{BASE_URL}sspseca.lista_carreras"
CONSULTA_OFERTA_URL = f"{BASE_URL}sspseca.consulta_oferta"
NUM_WORKERS = 29

# Configuración de ciclos a procesar
CICLOS_RECIENTES_A_ACTUALIZAR = 1  # Cuántos ciclos recientes actualizar cada 5 minutos
MAX_CICLOS_HISTORICOS = 10  # Máximo de ciclos históricos a scrapear inicialmente

ERROR_LOG_FILE = "errores_scraper.json"  # Archivo para guardar errores

# --- Funciones de Parseo y Scrapeo (Asíncronas) ---

async def get_initial_options_async(client: httpx.AsyncClient):
    """
    Obtiene todos los ciclos y centros universitarios de forma asíncrona.
    """
    print("FASE 1: Obteniendo y filtrando la lista de ciclos y centros...")
    try:
        response = await client.get(FORMA_CONSULTA_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Parseo de Ciclos
        ciclos = {}
        ciclo_seleccionado = soup.find('select', {'name': 'ciclop'})
        if ciclo_seleccionado:
            for option in ciclo_seleccionado.find_all('option'):
                value = option.get('value')
                text = ' '.join(option.text.split())
                
                if not value or not value.isdigit() or len(value) != 6:
                    continue
                
                year = value[:4]
                suffix_code = value[4:]
                
                new_name = None
                if suffix_code == "10":
                    new_name = f"{year}A"
                elif suffix_code == "20":
                    new_name = f"{year}B"
                elif suffix_code == "80":
                    new_name = f"{year}V"
                
                if new_name:
                    ciclos[value] = {"nombre": new_name}
        
        # Parseo de Centros
        centros = {}
        centro_seleccionado = soup.find('select', {'name': 'cup'})
        if centro_seleccionado:
            for option in centro_seleccionado.find_all('option'):
                value = option.get('value', '').strip()

                if option.contents:
                    text = option.contents[0].strip()  
                else:
                    text = option.get_text(strip=True)

                if not value or not text:
                    continue

                # Separa el código del nombre con “ - ”
                parts = text.split(' - ', 1)
                if len(parts) == 2:
                    code, name = parts
                else:
                    code, name = value, text

                name = name.strip().replace('\xa0', ' ')

                centros[value] = {"nombre": name, "carreras": {}}

        
        print(f"-> Encontrados {len(ciclos)} ciclos (después de filtrar) y {len(centros)} centros.")
        return ciclos, centros
    
    except httpx.RequestError as e:
        print(f"Error fatal al obtener opciones iniciales: {e}")
        return None, None

async def get_carreras_for_centro_async(client: httpx.AsyncClient, centro_code):
    """
    Obtiene todas las carreras para un centro universitario específico.
    """
    carreras = {}
    try:
        url = f"{LISTA_CARRERAS_URL}?cup={centro_code}"
        response = await client.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a'): # type: ignore
            href = link.get('href', '')
            if 'javascript:asigna' in href:
                try:
                    params_str = href.split('(')[1].split(')')[0]
                    params = [p.strip().strip("'") for p in params_str.split(',', 1)]
                    if len(params) == 2:
                        carrera_code, carrera_name = params
                        carreras[carrera_code] = {"nombre": carrera_name}
                except (IndexError, ValueError):
                    continue
        return carreras
    except httpx.RequestError:
        return {}

def parse_course_data(soup):
    """
    Extrae la información de las materias de una página de resultados. (Síncrono)
    """
    courses_on_page = []
    main_table = soup.find('table', {'border': '1', 'cellspacing': '0', 'cellpadding': '0'})
    if not main_table: return []

    for row in main_table.find_all('tr')[2:]:
        cells = row.find_all('td')
        if len(cells) < 9: continue

        schedule_info = []
        schedule_table = cells[7].find('table')
        if schedule_table:
            for schedule_row in schedule_table.find_all('tr'):
                schedule_cells = schedule_row.find_all('td')
                if len(schedule_cells) == 6:
                    schedule_info.append({
                        "sesion": schedule_cells[0].get_text(strip=True), "horas": schedule_cells[1].get_text(strip=True),
                        "dias": schedule_cells[2].get_text(strip=True), "edificio": schedule_cells[3].get_text(strip=True),
                        "aula": schedule_cells[4].get_text(strip=True), "periodo": schedule_cells[5].get_text(strip=True),
                    })
        
        professor_info = []
        prof_name_cell = row.select_one('td:nth-of-type(9) table tr td:nth-of-type(2)')
        prof_ses_cell = row.select_one('td:nth-of-type(9) table tr td:nth-of-type(1)')
        if prof_name_cell and prof_ses_cell:
            professor_info.append({
                "sesion": prof_ses_cell.get_text(strip=True), "nombre": prof_name_cell.get_text(strip=True)
            })

        courses_on_page.append({
            "nrc": cells[0].get_text(strip=True), "clave": cells[1].get_text(strip=True),
            "materia": cells[2].get_text(strip=True), "seccion": cells[3].get_text(strip=True),
            "creditos": cells[4].get_text(strip=True), "cupos": cells[5].get_text(strip=True),
            "disponibles": cells[6].get_text(strip=True), "horarios": schedule_info,
            "profesores": professor_info
        })
    return courses_on_page

async def get_courses_for_carrera_async(
    client: httpx.AsyncClient, 
    ciclo_code, 
    cup, 
    majrp, 
):
    """
    Obtiene todos los cursos para una combinación, paginando de 200 en 200.
    """
    all_courses = []
    p_start = 0
    while True:
        payload = {
            'ciclop': ciclo_code, 'cup': cup, 'majrp': majrp, 'mostrarp': '200', 'p_start': str(p_start)
        }
        try:
            response = await client.post(CONSULTA_OFERTA_URL, data=payload, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            courses_from_page = parse_course_data(soup)
            
            if not courses_from_page: 
                break
            all_courses.extend(courses_from_page)

            if "FIN DEL REPORTE" in response.text or not soup.find('input', {'value': '200 Próximos'}):
                break
            
            p_start += 200
            await asyncio.sleep(0.5) # Pequeña pausa
        except httpx.RequestError as e:
            print(f"\n  -> ADVERTENCIA: Error en la solicitud de cursos: {e}. Omitiendo esta carrera.")
            print(f"     Payload: {payload}\n")
            
            break
    return all_courses

# --- Lógica de Base de Datos y Orquestación ---

def check_ciclo_has_data(session: Session, ciclo_code: str) -> bool:
    """
    Verifica si existe algún dato (secciones) para un ciclo específico.
    """
    # Primero obtener el nombre formateado del ciclo
    year = ciclo_code[:4]
    suffix_code = ciclo_code[4:]
    
    ciclo_nombre = None
    if suffix_code == "10":
        ciclo_nombre = f"{year}A"
    elif suffix_code == "20":
        ciclo_nombre = f"{year}B"
    elif suffix_code == "80":
        ciclo_nombre = f"{year}V"
    
    if not ciclo_nombre:
        return False
    
    # Buscar el ciclo en la BD
    ciclo_obj = session.exec(select(Ciclo).where(Ciclo.nombre == ciclo_nombre)).first()
    if not ciclo_obj:
        return False
    
    # Verificar si hay secciones para este ciclo
    seccion = session.exec(select(Seccion).where(Seccion.id_ciclo == ciclo_obj.id).limit(1)).first()
    return seccion is not None

def get_or_create(session, model, defaults=None, **kwargs):
    """
    Función helper para buscar un objeto o crearlo si no existe.
    """
    instance = session.exec(select(model).filter_by(**kwargs)).first()
    if instance:
        return instance, False
    else:
        params = {**kwargs, **(defaults or {})}
        instance = model(**params)
        session.add(instance)
        session.commit()
        session.refresh(instance)
        # print(f"     -> Creado nuevo {model.__name__}: {params}")

        return instance, True

async def process_center_data(
    client: httpx.AsyncClient, 
    session: Session, 
    ciclo_code: str, 
    ciclo_info: dict, 
    centro_code: str, 
    centro_info: dict,
    carreras_filter: list[str] | None = None # <-- PARÁMETRO AÑADIDO
):
    """
    Procesa todas las carreras y cursos para un único centro y los guarda en la BD.
    Si 'carreras_filter' se proporciona, solo procesa carreras en esa lista.
    """
    print(f"  -> Procesando Centro: {centro_code} ({centro_info['nombre']}) : {ciclo_info['nombre']}")
    
    # 1. Obtener/Crear Ciclo
    ciclo_obj, _ = get_or_create(session, Ciclo, nombre=ciclo_info["nombre"])
    
    # 2. Obtener/Crear Centro (buscar por nombre, actualizar clave si no existe)
    centro_obj, creado = get_or_create(
        session, Centro, 
        nombre=centro_info["nombre"],
        defaults={"clave": centro_code}
    )
    # Si el centro ya existe pero no tiene clave, actualizarla
    if not creado and not centro_obj.clave:
        centro_obj.clave = centro_code
        session.add(centro_obj)
        session.commit()
        session.refresh(centro_obj)

    # 3. Obtener Carreras para este centro
    carreras = await get_carreras_for_centro_async(client, centro_code)
    if not carreras:
        print(f"  -> Centro {centro_code} no tiene carreras. Omitiendo.")
        return
    
    centro_info['carreras'] = carreras
    
    # --- LÓGICA DE FILTRADO AÑADIDA ---
    carreras_a_procesar: dict
    if carreras_filter:
        # Filtrar el dict 'carreras' para incluir solo las de 'carreras_filter'
        carreras_a_procesar = {
            code: info for code, info in carreras.items()
            if code in carreras_filter
        }
        if not carreras_a_procesar:
            print(f"     -> Ninguna de las carreras solicitadas ({', '.join(carreras_filter)}) se encontró en este centro. Omitiendo.")
            return
        print(f"     -> Aplicando filtro. Procesando {len(carreras_a_procesar)} carreras solicitadas.")
    else:
        # Comportamiento normal: procesar todas
        carreras_a_procesar = carreras
    # --- FIN DE LÓGICA DE FILTRADO ---

    # Bucle modificado para usar la lista filtrada
    for carrera_code, carrera_info in carreras_a_procesar.items():
#       print(f"    -> Carrera: {carrera_code} ({carrera_info['nombre']})")
        
        # 4. Obtener/Crear Carrera
        carrera_obj, _ = get_or_create(session, Carrera, clave=carrera_code, nombre=carrera_info["nombre"])
        
        # 4.1 Crear/Actualizar relación Centro-Carrera
        get_or_create(session, CentroCarreraLink, id_centro=centro_obj.id, id_carrera=carrera_obj.id)

        # 5. Obtener Cursos
        cursos_encontrados = await get_courses_for_carrera_async(
            client, 
            ciclo_code, 
            centro_code, 
            carrera_code,

        )
        
        if not cursos_encontrados:
#           print(f"     0 cursos para {carrera_code}.")
            continue
            
#       print(f"     ¡{len(cursos_encontrados)} cursos encontrados! Insertando en BD...")

        # 6. Iterar e insertar cursos (course)
        for course in cursos_encontrados:
            try:
                # 7. Obtener/Crear Materia
                materia_obj, _ = get_or_create(
                    session, Materia,
                    clave=course["clave"],
                    defaults={"nombre": course["materia"]}
                )
                carreramateria_obj, _ = get_or_create(
                    session, CarreraMateriaLink,
                    id_carrera=carrera_obj.id,
                    id_materia=materia_obj.id
                )
                
                # 8. Obtener/Crear Profesor
                prof_nombre = "SIN PROFESOR ASIGNADO" # Default
                if course["profesores"] and course["profesores"][0]["nombre"]:
                    prof_nombre = course["profesores"][0]["nombre"]

                profesor_obj, _ = get_or_create(session, Profesor, nombre=prof_nombre)

                # 9. Obtener/Crear Seccion (Usando el constraint 'nrc_ciclo_unicos')
                seccion_obj, seccion_creada = get_or_create(
                    session, Seccion,
                    nrc=course["nrc"],
                    id_ciclo=ciclo_obj.id,
                    defaults={
                        "numero": course["seccion"],
                        "id_materia": materia_obj.id,
                        "id_profesor": profesor_obj.id,
                        "id_centro": centro_obj.id,
                        "cupos": int(course["cupos"]),
                        "disponibilidad": int(course["disponibles"])
                    }
                )
                
                # Si la sección no es nueva, actualizamos cupos
                if not seccion_creada:
                    seccion_obj.cupos = int(course["cupos"])
                    seccion_obj.disponibilidad = int(course["disponibles"])
                    session.add(seccion_obj)
                    session.commit() # Guardar actualización de cupos
                    #print(f"     -> Actualizada Sección NRC {course['nrc']} con cupos y disponibilidad.")
                
                # 10. Insertar Sesiones (horarios)
                for horario in course["horarios"]:
                    if not horario["aula"] or not horario["edificio"]:
                        continue # Omitir horarios sin aula/edificio

                    # 11. Obtener/Crear Aula
                    aula_obj, _ = get_or_create(
                        session, Aula,
                        salon=horario["aula"],
                        edificio=horario["edificio"]
                    )
                    
                    # Parseo de fechas y horas
                    fecha_inicio_str, fecha_fin_str = horario["periodo"].split('-')
                    fecha_inicio_parts = [int(s) for s in fecha_inicio_str.strip().split('/')]
                    fecha_fin_parts = [int(s) for s in fecha_fin_str.strip().split('/')]
                    
                    fecha_inicio = datetime.date(day=fecha_inicio_parts[0], month=fecha_inicio_parts[1], year=fecha_inicio_parts[2] + 2000)
                    fecha_fin = datetime.date(day=fecha_fin_parts[0], month=fecha_fin_parts[1], year=fecha_fin_parts[2] + 2000)

                    hora_inicio_str, hora_fin_str = horario["horas"].split('-')
                    hora_inicio = datetime.time(hour=int(hora_inicio_str[:2]), minute=int(hora_inicio_str[2:]))
                    hora_fin = datetime.time(hour=int(hora_fin_str[:2]), minute=int(hora_fin_str[2:]))

                    dias_semana = horario["dias"].split(' ')
                    for i, c in enumerate(dias_semana, 1):
                        if c != ".":
                            # 12. Obtener/Crear Sesion
                            sesion_obj, _ = get_or_create(
                                session, Sesion,
                                id_seccion=seccion_obj.id,
                                id_aula=aula_obj.id,
                                fecha_inicio=fecha_inicio,
                                fecha_fin=fecha_fin,
                                hora_inicio=hora_inicio,
                                hora_fin=hora_fin,
                                dia_semana=i
                            )
            except Exception as e:
                print(f"Error procesando NRC {course.get('nrc')}: {e}")
                session.rollback() # Revertir cambios de este curso
            
        # Commit al final de cada carrera
        session.commit()

async def center_worker(queue: asyncio.Queue, client: httpx.AsyncClient):
    """
    Worker que consume centros de la cola y los procesa.
    """
    # Cada worker crea su propia sesión de BD
    with Session(engine) as session:
        while True:
            try:
                job = await queue.get()
                if job is None:
                    break # Señal de "None" para terminar
                
                # --- MODIFICADO para aceptar el filtro ---
                ciclo_code, ciclo_info, centro_code, centro_info, carreras_filter = job
                await process_center_data(
                    client, session, 
                    ciclo_code, ciclo_info, 
                    centro_code, centro_info, 
                    carreras_filter # <-- Pasar el filtro
                )
                print(f"    -> Centro {centro_code} ({centro_info['nombre']}) procesado : {ciclo_info['nombre']}")
            except Exception as e:
                print(f"Error en worker procesando {job} : {e}")
            finally:
                queue.task_done()

async def scrape_and_update_db(
    lock: asyncio.Lock, 
    client: httpx.AsyncClient,
    num_ciclos_recientes: int = CICLOS_RECIENTES_A_ACTUALIZAR,
    inicial: bool = False,
    force_historical: bool = False
):
    """
    Esta es la función principal que se llama desde main.py
    
    Args:
        lock: Lock asíncrono para prevenir scraping concurrente
        client: Cliente HTTP asíncrono
        num_ciclos_recientes: Número de ciclos más recientes a procesar
    inicial: Si es True, también procesa ciclos históricos sin datos
    force_historical: Si es True, fuerza el re-scrapeo de ciclos históricos (ignora si ya tienen datos)
    """
    if lock.locked():
        print("Scrapeo ya en curso. Omitiendo esta ejecución.")
        return

    async with lock:
        print("--- INICIANDO PROCESO DE SCRAPEO Y ACTUALIZACIÓN ---")
        try:
            ciclos, centros = await get_initial_options_async(client)
            if not ciclos or not centros:
                print("No se pudo obtener la configuración inicial. Abortando.")
                return

            # Obtener los N ciclos más recientes
            
            ciclos_recientes = list(ciclos.items())[:num_ciclos_recientes]
            #ciclos_recientes = list(ciclos.items())[2:3]
            ciclos_a_procesar = ciclos_recientes.copy()
            ciclos_a_procesar = [('202520', {'nombre': '2025B'})]
            ciclos_a_procesar = {}
            
            print("--- CICLOS A PROCESAR INICIALES ---")
            print(ciclos_a_procesar)
            # Lógica para ciclos históricos
            if force_historical:
                print("\n[ACTUALIZACIÓN HISTÓRICA FORZADA] Se forzará el re-scrapeo de ciclos históricos.")
                ciclos_historicos_forzados = list(ciclos.items())[num_ciclos_recientes:MAX_CICLOS_HISTORICOS]
                print(f"  -> Se agregarán {len(ciclos_historicos_forzados)} ciclos históricos (forzados).")
                ciclos_a_procesar.extend(ciclos_historicos_forzados)
            elif inicial:
                # Sólo agregar los ciclos que aún no tienen datos
                print(f"\n[SCRAPEO INICIAL] Verificando ciclos históricos sin datos...")
                with Session(engine) as session:
                    ciclos_historicos = []
                    for ciclo_code, ciclo_info in list(ciclos.items())[num_ciclos_recientes:MAX_CICLOS_HISTORICOS]:
                        if not check_ciclo_has_data(session, ciclo_code):
                            ciclos_historicos.append((ciclo_code, ciclo_info))
                            print(f"  -> Ciclo {ciclo_info['nombre']} sin datos. Será scrapeado.")
                    if ciclos_historicos:
                        print(f"[SCRAPEO INICIAL] Se scrapearan {len(ciclos_historicos)} ciclos históricos adicionales.")
                        ciclos_a_procesar.extend(ciclos_historicos)
                    else:
                        print("[SCRAPEO INICIAL] Todos los ciclos históricos ya tienen datos.")

            if not ciclos_a_procesar:
                print("No hay ciclos para procesar.")
                return

            print(f"\nTotal de ciclos a procesar: {len(ciclos_a_procesar)}")
            for _, info in ciclos_a_procesar:
                print(f"  - {info['nombre']}")

            queue = asyncio.Queue()

            # Iniciar workers
            workers = [
                asyncio.create_task(center_worker(queue, client)) 
                for _ in range(NUM_WORKERS)
            ]

            print(f"\nIniciando {NUM_WORKERS} workers...")

            for ciclo_code, ciclo_info in ciclos_a_procesar:
                print(f"\n--- PROCESANDO CICLO: {ciclo_code} ({ciclo_info['nombre']}) ---")
                
                for centro_code, centro_info in centros.items():
                    # Poner el trabajo en la cola
                    await queue.put((ciclo_code, ciclo_info, centro_code, centro_info, None))

            # Poner señales de "None" en la cola para detener a los workers
            for _ in range(NUM_WORKERS):
                await queue.put(None)

            # Esperar a que toda la cola sea procesada
            await queue.join()
            
            # Esperar a que los tasks de los workers terminen
            await asyncio.gather(*workers)

            print("--- PROCESO DE SCRAPEO Y ACTUALIZACIÓN COMPLETADO ---")

        except Exception as e:
            print(f"Error fatal durante el scrapeo: {e}")


# --- FUNCIÓN DE SCRAPEO DIRIGIDO RÁPIDO ---
async def scrape_specific_materia(
    client: httpx.AsyncClient,
    ciclo_nombre: str,
    centro_clave: str,
    carrera_codigo: str,
    materia_clave: str
):
    """
    Scrapea una materia específica sin usar el lock global.
    Retorna True si se encontró y procesó la materia, False si no.
    
    Args:
        centro_clave: Código cup del centro (ej: 'D' para CUCEI)
    """
    print(f"\n--- SCRAPEO DIRIGIDO: {materia_clave} en {centro_clave} - {ciclo_nombre} ---")
    
    try:
        # 1. Obtener mapeos
        ciclos, centros = await get_initial_options_async(client)
        if not ciclos or not centros:
            print("No se pudo obtener la configuración inicial.")
            return False

        # 2. Encontrar código del ciclo
        target_ciclo_code = None
        target_ciclo_info = None
        for code, info in ciclos.items():
            if info["nombre"] == ciclo_nombre:
                target_ciclo_code = code
                target_ciclo_info = info
                break
        
        if not target_ciclo_code or not target_ciclo_info:
            print(f"Ciclo '{ciclo_nombre}' no encontrado.")
            return False

        # 3. Verificar que el centro existe en SIIAU y obtener su info
        if centro_clave not in centros:
            print(f"Centro con clave '{centro_clave}' no encontrado en SIIAU.")
            return False
        
        target_centro_code = centro_clave
        target_centro_info = centros[centro_clave]

        # 4. Obtener carreras del centro
        carreras = await get_carreras_for_centro_async(client, target_centro_code)
        if carrera_codigo not in carreras:
            print(f"Carrera '{carrera_codigo}' no encontrada en {target_centro_info['nombre']}.")
            return False

        # 5. Obtener cursos de la carrera
        print(f"Obteniendo cursos para {carrera_codigo}...")
        cursos = await get_courses_for_carrera_async(
            client, target_ciclo_code, target_centro_code, carrera_codigo
        )

        # 6. Filtrar solo la materia solicitada
        cursos_materia = [c for c in cursos if c["clave"] == materia_clave]
        
        if not cursos_materia:
            print(f"Materia '{materia_clave}' no encontrada en la oferta académica.")
            return False

        print(f"Encontradas {len(cursos_materia)} secciones de {materia_clave}. Procesando...")

        # 7. Procesar con la BD
        with Session(engine) as session:
            # Obtener/Crear objetos base
            ciclo_obj, _ = get_or_create(session, Ciclo, nombre=target_ciclo_info["nombre"])
            centro_obj, creado = get_or_create(
                session, Centro,
                nombre=target_centro_info["nombre"],
                defaults={"clave": target_centro_code}
            )
            # Si el centro ya existe pero no tiene clave, actualizarla
            if not creado and not centro_obj.clave:
                centro_obj.clave = target_centro_code
                session.add(centro_obj)
                session.commit()
                session.refresh(centro_obj)
            
            carrera_obj, _ = get_or_create(session, Carrera, clave=carrera_codigo, nombre=carreras[carrera_codigo]["nombre"])

            # Procesar cada sección de la materia
            for course in cursos_materia:
                try:
                    # Obtener/Crear Materia
                    materia_obj, _ = get_or_create(
                        session, Materia,
                        clave=course["clave"],
                        defaults={"nombre": course["materia"]}
                    )
                    carreramateria_obj, _ = get_or_create(
                        session, CarreraMateriaLink,
                        id_carrera=carrera_obj.id,
                        id_materia=materia_obj.id
                    )
                    

                    # Obtener/Crear Profesor
                    prof_nombre = "SIN PROFESOR ASIGNADO"
                    if course["profesores"] and course["profesores"][0]["nombre"]:
                        prof_nombre = course["profesores"][0]["nombre"]
                    profesor_obj, _ = get_or_create(session, Profesor, nombre=prof_nombre)

                    # Obtener/Crear Seccion
                    seccion_obj, seccion_creada = get_or_create(
                        session, Seccion,
                        nrc=course["nrc"],
                        id_ciclo=ciclo_obj.id,
                        defaults={
                            "numero": course["seccion"],
                            "id_materia": materia_obj.id,
                            "id_profesor": profesor_obj.id,
                            "id_centro": centro_obj.id,
                            "cupos": int(course["cupos"]),
                            "disponibilidad": int(course["disponibles"])
                        }
                    )
                    
                    if not seccion_creada:
                        seccion_obj.cupos = int(course["cupos"])
                        seccion_obj.disponibilidad = int(course["disponibles"])
                        session.add(seccion_obj)
                        session.commit()
                    
                    # Insertar Sesiones
                    for horario in course["horarios"]:
                        if not horario["aula"] or not horario["edificio"]:
                            continue

                        aula_obj, _ = get_or_create(
                            session, Aula,
                            salon=horario["aula"],
                            edificio=horario["edificio"]
                        )
                        
                        fecha_inicio_str, fecha_fin_str = horario["periodo"].split('-')
                        fecha_inicio_parts = [int(s) for s in fecha_inicio_str.strip().split('/')]
                        fecha_fin_parts = [int(s) for s in fecha_fin_str.strip().split('/')]
                        
                        fecha_inicio = datetime.date(day=fecha_inicio_parts[0], month=fecha_inicio_parts[1], year=fecha_inicio_parts[2] + 2000)
                        fecha_fin = datetime.date(day=fecha_fin_parts[0], month=fecha_fin_parts[1], year=fecha_fin_parts[2] + 2000)

                        hora_inicio_str, hora_fin_str = horario["horas"].split('-')
                        hora_inicio = datetime.time(hour=int(hora_inicio_str[:2]), minute=int(hora_inicio_str[2:]))
                        hora_fin = datetime.time(hour=int(hora_fin_str[:2]), minute=int(hora_fin_str[2:]))

                        dias_semana = horario["dias"].split(' ')
                        for i, c in enumerate(dias_semana, 1):
                            if c != ".":
                                sesion_obj, _ = get_or_create(
                                    session, Sesion,
                                    id_seccion=seccion_obj.id,
                                    id_aula=aula_obj.id,
                                    fecha_inicio=fecha_inicio,
                                    fecha_fin=fecha_fin,
                                    hora_inicio=hora_inicio,
                                    hora_fin=hora_fin,
                                    dia_semana=i
                                )
                except Exception as e:
                    print(f"Error procesando NRC {course.get('nrc')}: {e}")
                    session.rollback()
            
            session.commit()
        
        print(f"✓ Scrapeo dirigido de {materia_clave} completado exitosamente.")
        return True

    except Exception as e:
        print(f"Error en scrapeo dirigido: {e}")
        return False

