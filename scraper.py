import requests
from bs4 import BeautifulSoup
import json

def parse_course_data(soup):
    """
    Extrae la información de las materias de una página HTML parseada.
    """
    courses_on_page = []
    main_table = soup.find('table', {'border': '1', 'cellspacing': '0', 'cellpadding': '0'})

    if not main_table:
        return []

    for row in main_table.find_all('tr')[2:]:
        cells = row.find_all('td')
        if len(cells) < 9:
            continue
        
        # --- Extracción de Horarios (método actual funciona bien) ---
        schedule_info = []
        schedule_table = cells[7].find('table')
        if schedule_table:
            for schedule_row in schedule_table.find_all('tr'):
                schedule_cells = schedule_row.find_all('td')
                if len(schedule_cells) == 6:
                    schedule_info.append({
                        "sesion": schedule_cells[0].get_text(strip=True),
                        "horas": schedule_cells[1].get_text(strip=True),
                        "dias": schedule_cells[2].get_text(strip=True),
                        "edificio": schedule_cells[3].get_text(strip=True),
                        "aula": schedule_cells[4].get_text(strip=True),
                        "periodo": schedule_cells[5].get_text(strip=True),
                    })
        
        # --- NUEVO MÉTODO DE EXTRACCIÓN DE PROFESORES ---
        professor_info = []
        # Usamos un selector CSS para ir directamente al dato. Es más robusto.
        # 'td:nth-of-type(9)' -> la 9na celda de la fila.
        # 'table tr td' -> la celda dentro de la tabla anidada.
        prof_name_cell = row.select_one('td:nth-of-type(9) table tr td:nth-of-type(2)')
        prof_ses_cell = row.select_one('td:nth-of-type(9) table tr td:nth-of-type(1)')

        if prof_name_cell and prof_ses_cell:
            professor_info.append({
                "sesion": prof_ses_cell.get_text(strip=True),
                "nombre": prof_name_cell.get_text(strip=True)
            })

        course = {
            "nrc": cells[0].get_text(strip=True),
            "clave": cells[1].get_text(strip=True),
            "materia": cells[2].get_text(strip=True),
            "seccion": cells[3].get_text(strip=True),
            "creditos": cells[4].get_text(strip=True),
            "cupos": cells[5].get_text(strip=True),
            "disponibles": cells[6].get_text(strip=True),
            "horarios": schedule_info,
            "profesores": professor_info
        }
        courses_on_page.append(course)

    return courses_on_page

def scrape_course_offerings():
    """
    Función principal para realizar el scraping de la oferta académica.
    """
    ciclop = "202520"
    cup = "D"
    majrp = "ICOM"
    mostrarp = "100"

    base_url = 'http://consulta.siiau.udg.mx/wco/sspseca.consulta_oferta'
    session = requests.Session()
    
    all_courses = []
    p_start = 0
    
    print("Iniciando scraping de la oferta académica...")

    while True:
        payload = {
            'ciclop': ciclop, 'cup': cup, 'majrp': majrp, 'crsep': '',
            'materiap': '', 'horaip': '', 'horafp': '', 'edifp': '',
            'aulap': '', 'ordenp': '0', 'mostrarp': mostrarp, 'p_start': str(p_start)
        }

        try:
            print(f"Consultando página con p_start={p_start}...")
            response = session.post(base_url, data=payload, timeout=20)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            
            courses_from_page = parse_course_data(soup)
            if not courses_from_page:
                print("No se encontraron más materias en la página. Finalizando.")
                break
            
            all_courses.extend(courses_from_page)
            print(f"-> Se encontraron y procesaron {len(courses_from_page)} materias.")

            if "FIN DEL REPORTE" in response.text:
                print("Se ha llegado al final del reporte.")
                break
            
            if not soup.find('input', {'value': '100 Próximos'}):
                print("No se encontró el botón '100 Próximos'. Finalizando.")
                break

            p_start += int(mostrarp)

        except requests.exceptions.RequestException as e:
            print(f"Error durante la solicitud HTTP: {e}")
            break

    output_file = 'oferta_academica.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_courses, f, indent=4, ensure_ascii=False)
        print(f"\n¡Éxito! 🚀 Se han guardado un total de {len(all_courses)} materias en el archivo '{output_file}'")
    except IOError as e:
        print(f"Error al escribir en el archivo JSON: {e}")

if __name__ == "__main__":
    scrape_course_offerings()
