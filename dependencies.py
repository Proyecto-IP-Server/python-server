from database import SessionDep
from sqlmodel import select
from fastapi import HTTPException, Depends
from typing import Annotated
from lifespan import alias_a_centro
from models import *

# --- Dependencias de Endpoints ---

def validar_ciclo(session: SessionDep, ciclo: str) -> int:
    id_ciclo = session.exec(select(Ciclo.id).where(
        Ciclo.nombre == ciclo)).first()
    if id_ciclo is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    return id_ciclo


def validar_materia(session: SessionDep, materia: str) -> int:
    id_materia = session.exec(select(Materia.id).where(
        Materia.clave == materia)).first()
    if id_materia is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return id_materia


def materia_opcional(session: SessionDep, materia: str | None = None) -> int | None:
    if materia is None:
        return None
    return validar_materia(session, materia)


def validar_centro(session: SessionDep, centro: str) -> int:
    if centro in alias_a_centro:
        centro = alias_a_centro[centro]

    id_centro = session.exec(select(Centro.id).where(
        Centro.nombre == centro)).first()
    if id_centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    return id_centro


def centro_opcional(session: SessionDep, centro: str | None = None) -> int | None:
    if centro is None:
        return None
    return validar_centro(session, centro)


def obtener_clave_centro(centro_nombre: str, session: SessionDep) -> tuple[str, str]:
    if centro_nombre in alias_a_centro:
        centro_nombre = alias_a_centro[centro_nombre]
    centro = session.exec(select(Centro).where(
        Centro.nombre == centro_nombre)).first()
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


def validar_alumno(session: SessionDep, correo_alumno: str) -> int:
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
        raise HTTPException(status_code=500, detail="Error")

    return alumno.id


def validar_profesor(session: SessionDep, profesor: str) -> int:
    id_profesor = session.exec(select(Profesor.id).where(
        Profesor.nombre == profesor)).first()
    if id_profesor is None:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")
    return id_profesor


def profesor_opcional(session: SessionDep, profesor: str | None = None) -> int | None:
    if profesor is None:
        return None
    return validar_profesor(session, profesor)


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
MateriaOptDep = Annotated[int | None, Depends(materia_opcional)]
CentroOptDep = Annotated[int | None, Depends(centro_opcional)]
ProfesorOptDep = Annotated[int | None, Depends(profesor_opcional)]
CarreraOptDep = Annotated[int | None, Depends(carrera_opcional)]
