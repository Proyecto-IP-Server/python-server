from lifespan import app
from models import Carrera
from dependencies import *
from database import SessionDep
from sqlmodel import select, and_

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
    return session.exec(statement).all()

