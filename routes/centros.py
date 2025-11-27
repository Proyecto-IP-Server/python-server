from lifespan import app, centro_a_alias
from models import Centro
from database import SessionDep
from sqlmodel import select

@app.get("/centros/", response_model=list[str])
def read_centros(session: SessionDep):
    centros = session.exec(select(Centro.nombre)).all()
    return sorted([centro_a_alias.get(centro, centro) for centro in centros])

