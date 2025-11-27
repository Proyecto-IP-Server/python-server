from models import *
from dependencies import *
from lifespan import app
from fastapi import Query
@app.get("/profesores/{materia}", response_model=list[ProfesorPublic])
def read_profesores(
        session: SessionDep,
        materia: MateriaDep,
        offset: int = 0,
        limit: Annotated[int, Query(le=1000)] = 1000):

    stmt = select(Profesor).join(Seccion).where(
        Seccion.id_materia == materia
    )

    profesores = session.exec(stmt.distinct().offset(offset).limit(limit)).all()
    return profesores
