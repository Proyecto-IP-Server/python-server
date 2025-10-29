import datetime
import json
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Field, Relationship, Session, SQLModel, UniqueConstraint, create_engine, select
from contextlib import asynccontextmanager


class Ciclo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(index=True, unique=True)

class Centro(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(index=True)
    secciones: list["Seccion"] = Relationship(back_populates="centro")

class Carrera(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(index=True)

    materias: list["Materia"] = Relationship(back_populates="carrera")

class Profesor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    secciones: list["Seccion"] = Relationship(back_populates="profesor")

class Alumno(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    correo: str

class Materia(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    clave: str = Field(unique=True, index=True)
    nombre: str = Field()
    id_carrera: int = Field(foreign_key="carrera.id", index=True)
    carrera: Carrera = Relationship(back_populates="materias")

class Resena(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("id_profesor", "id_materia", "id_alumno", name="resenas_unicas"),
    )
    id: int | None = Field(default=None, primary_key=True)
    id_profesor : int = Field(foreign_key="profesor.id", index=True)
    id_materia : int = Field(foreign_key="materia.id", index=True)
    id_alumno : int = Field(foreign_key="alumno.id", index=True)
    fecha_creacion: datetime.datetime
    contenido : str
    satisfaccion : int

class Seccion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("nrc", "id_ciclo", name="nrc_ciclo_unicos"),
    )
    id: int | None = Field(default=None, primary_key=True)
    nrc: str = Field(index=True)
    numero: str
    id_ciclo: int | None = Field(
        default=None, foreign_key="ciclo.id", index=True)
    ciclo: Ciclo = Relationship()
    id_materia: int = Field(foreign_key="materia.id", index=True)
    materia: Materia = Relationship()
    id_profesor: int = Field(foreign_key="profesor.id", index=True)
    profesor: Profesor = Relationship(back_populates="secciones")
    id_centro: int = Field(foreign_key="centro.id", index=True)
    centro: Centro = Relationship(back_populates="secciones")
    sesiones: list["Sesion"] = Relationship(back_populates="seccion")
    disponibilidad: int = Field()
    cupos: int = Field()


class Aula(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    __table_args__ = (
        UniqueConstraint("salon", "edificio", name="aulas_unicas"),
    )
    salon: str = Field()
    edificio: str = Field()


class Sesion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    id_seccion: int = Field(foreign_key="seccion.id", index=True)
    seccion: Seccion = Relationship(back_populates="sesiones")
    id_aula: int = Field(foreign_key="aula.id", index=True)
    aula: Aula = Relationship()
    fecha_inicio: datetime.date
    fecha_fin: datetime.date
    hora_inicio: datetime.time
    hora_fin: datetime.time
    dia_semana: int


class MateriaPublic(BaseModel):
    clave: str
    nombre: str
    carrera: str


class SeccionPublic(BaseModel):
    numero: str
    nrc: str
    profesor: str
    centro: str
    sesiones: list["SesionPublic"]
    cupos: int
    disponibilidad: int


class SesionPublic(BaseModel):
    salon: str
    edificio: str
    fecha_inicio: datetime.date
    fecha_fin: datetime.date
    hora_inicio: datetime.time
    hora_fin: datetime.time
    dia_semana: int

class ResenaPublic(BaseModel):
    contenido: str
    satisfaccion: int
    profesor: str
    materia: str
    alumno: str


sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


def create_materias():
    try:
        with Session(engine) as session:
            with open('oferta_academica.json', 'r', encoding='utf-8') as f:
                course_data = json.load(f)
                for course in course_data:

                    ciclo = session.exec(select(Ciclo).where(
                        Ciclo.nombre == "2025B")).first()
                    if not ciclo:
                        ciclo = Ciclo(nombre="2025B")
                        session.add(ciclo)
                        session.commit()  # Guardar Ciclo

                    print("ciclo insertado")

                    # 2. Insertar Carrera (si no existe)
                    carrera = session.exec(select(Carrera).where(
                        Carrera.nombre == "ICOM")).first()
                    if not carrera:
                        carrera = Carrera(nombre="ICOM")
                        session.add(carrera)
                        session.commit()  # Guardar Carrera

                    print("carrera insertada")

                    centro = session.exec(select(Centro).where(
                        Centro.nombre == "CUCEI")).first()
                    if not centro:
                        centro = Centro(nombre="CUCEI")
                        session.add(centro)
                        session.commit()  # Guardar Carrera

                    print("centro insertado")

                    # 3. Insertar ClaveMateria (si no existe)
                    # 4. Insertar Materia (si no existe)
                    materia = session.exec(select(Materia).where(
                        Materia.clave == course["clave"])).first()
                    if not materia:
                        materia = Materia(
                            nombre=course["materia"],
                            clave=course["clave"],
                            id_carrera=carrera.id,
                        )
                        session.add(materia)
                        session.commit()  # Guardar Materia

                    print("materia insertada")

                    # 5. Insertar Seccion
                    prof = course["profesores"][0]
                    profesor = session.exec(select(Profesor).where(
                        Profesor.nombre == prof["nombre"])).first()
                    if not profesor:
                        profesor = Profesor(nombre=prof["nombre"])
                        session.add(profesor)
                        session.commit()  # Guardar Profesor
                    print("profesor insertado")

                    seccion = session.exec(select(Seccion).where(
                        Seccion.nrc == course["nrc"])).first()
                    if not seccion:
                        seccion = Seccion(
                            nrc=course["nrc"],
                            numero=course["seccion"],
                            id_materia=materia.id,
                            id_profesor=profesor.id,
                            id_centro=centro.id,
                            id_ciclo=ciclo.id,
                            cupos=course["cupos"],
                            disponibilidad=course["disponibles"]
                        )
                        session.add(seccion)
                        session.commit()  # Guardar Sección

                    print("seccion insertada")

                    # 6. Insertar Profesor

                    # 8. Insertar Sesiones
                    for horario in course["horarios"]:
                        aula = session.query(Aula).filter(
                            Aula.salon == horario["aula"], Aula.edificio == horario["edificio"]).first()
                        if not aula:
                            aula = Aula(
                                salon=horario["aula"], edificio=horario["edificio"])
                            session.add(aula)
                            session.commit()  # Guardar Aula
                        fecha_inicio, fecha_fin = horario["periodo"].split('-')
                        fecha_inicio = fecha_inicio.strip()
                        fecha_fin = fecha_fin.strip()
                        fecha_inicio = [int(s)
                                        for s in fecha_inicio.split('/')]
                        fecha_fin = [int(s) for s in fecha_fin.split('/')]
                        fecha_fin = datetime.date(
                            day=fecha_fin[0], month=fecha_fin[1], year=fecha_fin[2] + 2000)
                        fecha_inicio = datetime.date(
                            day=fecha_inicio[0], month=fecha_inicio[1], year=fecha_inicio[2] + 2000)
                        print(fecha_inicio, fecha_fin)
                        hora_inicio, hora_fin = horario["horas"].split('-')
                        hora_inicio = datetime.time(
                            hour=int(hora_inicio[:2]), minute=int(hora_inicio[2:]))
                        hora_fin = datetime.time(
                            hour=int(hora_fin[:2]), minute=int(hora_fin[2:]))

                        dias_semana = horario["dias"].split(' ')

                        for i, c in enumerate(dias_semana, 1):
                            if c != ".":
                                sesion = session.exec(select(Sesion).where(Sesion.id_seccion == seccion.id, Sesion.id_aula == seccion.id, Sesion.fecha_inicio ==
                                                      fecha_inicio, Sesion.fecha_fin == fecha_fin, Sesion.hora_inicio == hora_inicio, Sesion.hora_fin == hora_fin, Sesion.dia_semana == i)).first()
                                if not sesion:
                                    sesion = Sesion(
                                        id_seccion=seccion.id,
                                        id_aula=aula.id,
                                        fecha_inicio=fecha_inicio,
                                        fecha_fin=fecha_fin,
                                        hora_inicio=hora_inicio,
                                        hora_fin=hora_fin,
                                        dia_semana=i
                                    )
                                    session.add(sesion)
                        session.commit()  # Guardar Sesión

    except Exception as e:
        print(e)
        pass


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def validar_ciclo(ciclo: str, session: SessionDep) -> int:
    id_ciclo = session.exec(select(Ciclo.id).where(
        Ciclo.nombre == ciclo)).first()
    if id_ciclo is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    return id_ciclo


def validar_materia(materia: str, session: SessionDep) -> int:
    id_materia = session.exec(select(Materia.id).where(
        Materia.clave == materia)).first()
    if id_materia is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return id_materia


CicloDep = Annotated[int, Depends(validar_ciclo)]
MateriaDep = Annotated[int, Depends(validar_materia)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    create_materias()
    yield

app = FastAPI(lifespan=lifespan)


@app.get("/materias/", response_model=list[MateriaPublic])
def read_materias(
        session: SessionDep,
        carrera: str | None = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):

    stmt = select(Materia)
    if carrera is not None:
        stmt = stmt.join(Carrera).where(Carrera.nombre == carrera)

    materias = session.exec(stmt.offset(offset).limit(limit)).all()

    result: list[MateriaPublic] = []
    for m in materias:

        result.append(MateriaPublic(
            clave=m.clave,
            nombre=m.nombre,
            carrera=m.carrera.nombre
        ))

    return result


@app.get("/materia/{materia}/{ciclo}/secciones", response_model=list[SeccionPublic])
def read_secciones_de_materia(session: SessionDep, materia: MateriaDep, ciclo: CicloDep):
    # obtener secciones de la materia
    secciones = session.exec(select(Seccion).where(
        Seccion.id_materia == materia, Seccion.id_ciclo == ciclo)).all()
    secciones_public: list[SeccionPublic] = []
    for s in secciones or []:
        # transformar sesiones de la sección
        sesiones_public: list[SesionPublic] = []
        for ses in s.sesiones or []:
            # aula puede ser None, manejamos eso

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
    m = session.get(Materia, materia)
    return MateriaPublic(
                clave=m.clave,
                nombre=m.nombre,
                carrera=m.carrera.nombre
            )

@app.get("/resenas/", response_model=list[ResenaPublic])
def read_resenas(
        session: SessionDep,
        profesor: str | None = None,
        materia: str | None = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):

    stmt = select(Materia)
    if carrera is not None:
        stmt = stmt.join(Carrera).where(Carrera.nombre == carrera)

    materias = session.exec(stmt.offset(offset).limit(limit)).all()

    result: list[MateriaPublic] = []
    for m in materias:

        result.append(MateriaPublic(
            clave=m.clave,
            nombre=m.nombre,
            carrera=m.carrera.nombre
        ))

    return result


