from models import *
from dependencies import *
from lifespan import app
from fastapi import Query
from sqlmodel import and_
@app.get("/materias/", response_model=list[MateriaPublic])
def read_materias(
        session: SessionDep,
        ciclo: CicloOptDep = None,
        carrera: CarreraOptDep = None,
        centro: CentroOptDep = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=1000)] = 1000):

    stmt = select(Materia)
    if ciclo or centro:
        stmt = stmt.join(Seccion)
    if ciclo is not None:
        stmt = stmt.where(
        Seccion.id_ciclo == ciclo
    )

    if carrera is not None:
        stmt = stmt.join(CarreraMateriaLink,
                         and_(CarreraMateriaLink.id_carrera == carrera,
                              CarreraMateriaLink.id_materia == Materia.id))

    if centro is not None:
        stmt = stmt.where(Seccion.id_centro == centro)

    materias = session.exec(stmt.distinct().offset(offset).limit(limit)).all()
    return materias

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
    return session.get(Materia, materia)
