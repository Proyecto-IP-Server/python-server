from lifespan import app
from models import Carrera
from dependencies import *
from database import SessionDep
from sqlmodel import select, and_

@app.get("/carreras/", response_model=list[CarreraPublic])
def read_carreras(session: SessionDep, ciclo: CicloOptDep = None, centro: CentroOptDep = None):
    on_clause = and_(
            Seccion.id_materia == CarreraMateriaLink.id_materia,
        )
    if ciclo is not None:
        on_clause = and_(on_clause,
            Seccion.id_ciclo == ciclo
        )
    if centro is not None:
        on_clause = and_(on_clause,
            Seccion.id_centro == centro
        )
        
    statement = (
        select(Carrera)
        .select_from(Carrera)
        .join(CentroCarreraLink, CentroCarreraLink.id_carrera == Carrera.id) # type: ignore
        .join(CarreraMateriaLink, CarreraMateriaLink.id_carrera == Carrera.id) # type: ignore
        .join(Seccion, on_clause)
        .where(CentroCarreraLink.id_centro == centro)
        .distinct()
    )
    return session.exec(statement).all()

