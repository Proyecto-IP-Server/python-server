from lifespan import app
from models import Ciclo
from database import SessionDep
from sqlmodel import select

@app.get("/ciclos/", response_model=list[str])
def read_ciclos(session: SessionDep):
    ciclos = session.exec(select(Ciclo.nombre)).all()
    return sorted(ciclos, reverse=True)

