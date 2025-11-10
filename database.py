from typing import Annotated
from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args, pool_size=20, max_overflow=20)

def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]

def create_db_and_tables():
    # Importar los modelos aqui asegura que esten registrados en SQLModel.metadata
    import models 
    SQLModel.metadata.create_all(engine)