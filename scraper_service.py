import datetime
import asyncio
import httpx
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
NUM_WORKERS = 15  # Procesar 4 centros concurrentemente

CANT_CICLOS_A_PROCESAR = 9  # Limitar a 1 ciclo (el más reciente)
CICLOS_A_PROCESAR = None  # CANT_CICLOS_A_PROCESAR DEBE SER None: 0 para 2025A, 1 para 2025V, 2 para 2025B, etc.

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
        
        for link in soup.find_all('a'):
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

async def get_courses_for_carrera_async(client: httpx.AsyncClient, ciclo_code, cup, majrp):
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
    
    # 2. Obtener/Crear Centro
    centro_obj, _ = get_or_create(session, Centro, nombre=centro_info["nombre"])

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
        carrera_obj, _ = get_or_create(session, Carrera, nombre=carrera_info["nombre"])

        # 5. Obtener Cursos
        cursos_encontrados = await get_courses_for_carrera_async(client, ciclo_code, centro_code, carrera_code)
        
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
                    defaults={"nombre": course["materia"], "id_carrera": carrera_obj.id}
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

async def scrape_and_update_db(lock: asyncio.Lock, client: httpx.AsyncClient):
    """
    Esta es la función principal que se llama desde main.py
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



            # --- LIMITAR A 1 CICLO (EL MÁS RECIENTE) ---
            if CANT_CICLOS_A_PROCESAR is not None:
                ciclos_a_procesar = list(ciclos.items())[:CANT_CICLOS_A_PROCESAR]
            elif CICLOS_A_PROCESAR is not None:
                ciclos_a_procesar = [list(ciclos.items())[CICLOS_A_PROCESAR]]
            else:
                vacio = {}
                ciclos_a_procesar = list(vacio.items())
            if not ciclos_a_procesar:
                print("No hay ciclos para procesar.")
                return

            queue = asyncio.Queue()

            # Iniciar workers
            workers = [
                asyncio.create_task(center_worker(queue, client)) 
                for _ in range(NUM_WORKERS)
            ]

            print(f"Iniciando {NUM_WORKERS} workers...")

            for ciclo_code, ciclo_info in ciclos_a_procesar:
                print(f"\n--- PROCESANDO CICLO: {ciclo_code} ({ciclo_info['nombre']}) ---")
                
                for centro_code, centro_info in centros.items():
                    # Poner el trabajo en la cola
                    # --- MODIFICADO: Añade 'None' para el filtro de carreras ---
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


# --- NUEVA FUNCIÓN ---
async def scrape_and_update_targeted(
    lock: asyncio.Lock, 
    client: httpx.AsyncClient, 
    ciclo_nombre: str, 
    centros_nombres: list[str], 
    carreras_codigos: list[str]
):
    """
    Orquesta un proceso de scrapeo DIRIGIDO para centros y carreras específicas.
    """
    if lock.locked():
        print("Scrapeo ya en curso. Omitiendo esta ejecución.")
        return

    async with lock:
        print("--- INICIANDO PROCESO DE SCRAPEO DIRIGIDO ---")
        try:
            # 1. Obtener los mapeos de nombres a códigos
            ciclos, centros = await get_initial_options_async(client)
            if not ciclos or not centros:
                print("No se pudo obtener la configuración inicial. Abortando.")
                return

            # 2. Encontrar el código del ciclo solicitado
            target_ciclo_code = None
            target_ciclo_info = None
            for code, info in ciclos.items():
                if info["nombre"] == ciclo_nombre:
                    target_ciclo_code = code
                    target_ciclo_info = info
                    break
            
            if not target_ciclo_code:
                print(f"Ciclo '{ciclo_nombre}' no encontrado en SIIAU. Abortando.")
                return

            # 3. Filtrar los centros solicitados
            target_centros = [] # Lista de tuplas (code, info)
            for code, info in centros.items():
                if info["nombre"] in centros_nombres:
                    target_centros.append((code, info))
            
            if not target_centros:
                print(f"Ninguno de los centros solicitados ({', '.join(centros_nombres)}) fue encontrado. Abortando.")
                return

            # 4. Crear cola y workers
            queue = asyncio.Queue()
            workers = [asyncio.create_task(center_worker(queue, client)) for _ in range(NUM_WORKERS)]

            print(f"Iniciando {NUM_WORKERS} workers para {len(target_centros)} centros dirigidos...")

            # 5. Poner trabajos en la cola (esta vez con el filtro de carreras)
            for centro_code, centro_info in target_centros:
                await queue.put((
                    target_ciclo_code, 
                    target_ciclo_info, 
                    centro_code, 
                    centro_info, 
                    carreras_codigos  # <-- Aquí pasamos el filtro
                ))

            # 6. Enviar señales de fin a los workers
            for _ in range(NUM_WORKERS):
                await queue.put(None)
            
            await queue.join()
            await asyncio.gather(*workers)

            print("--- PROCESO DE SCRAPEO DIRIGIDO COMPLETADO ---")

        except Exception as e:
            print(f"Error fatal durante el scrapeo dirigido: {e}")

