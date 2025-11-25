import datetime
from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

# --- Modelos SQLModel (Tablas de Base de Datos) ---

class Ciclo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(index=True, unique=True)

class Centro(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    clave: str | None = Field(default=None, index=True)  # Código cup (solo para uso interno de refresh)
    nombre: str = Field(index=True, unique=True)
    secciones: list["Seccion"] = Relationship(back_populates="centro")

class CarreraMateriaLink(SQLModel, table=True):
    id_carrera: int = Field(foreign_key="carrera.id", primary_key=True)
    id_materia: int = Field(foreign_key="materia.id", primary_key=True)

class CentroCarreraLink(SQLModel, table=True):
    id_centro: int = Field(foreign_key="centro.id", primary_key=True)
    id_carrera: int = Field(foreign_key="carrera.id", primary_key=True)

class Carrera(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    clave: str = Field(index=True)
    nombre: str = Field()
    materias: list["Materia"] = Relationship(back_populates="carreras", link_model = CarreraMateriaLink)

class Profesor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    secciones: list["Seccion"] = Relationship(back_populates="profesor")

class Alumno(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    correo: str = Field(index=True, unique=True)

class Materia(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    clave: str = Field(unique=True, index=True)
    creditos: int = Field()
    nombre: str = Field()
    carreras: list["Carrera"] = Relationship(back_populates="materias", link_model = CarreraMateriaLink)



class Resena(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("id_profesor", "id_materia", "id_alumno", name="resenas_unicas"),
    )
    id: int | None = Field(default=None, primary_key=True)
    id_profesor : int = Field(foreign_key="profesor.id", index=True)
    id_materia : int = Field(foreign_key="materia.id", index=True)
    id_alumno : int = Field(foreign_key="alumno.id", index=True)
    fecha_creacion: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    contenido : str
    satisfaccion : int = Field(ge=1, le=5)
    
    profesor: Profesor = Relationship()
    materia: Materia = Relationship()
    alumno: Alumno = Relationship()

class ResenaPendiente(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("id_profesor", "id_materia", "id_alumno", name="pendiente_unica_por_tupla"),
    )
    id: int | None = Field(default=None, primary_key=True)
    id_profesor : int = Field(foreign_key="profesor.id", index=True)
    id_materia : int = Field(foreign_key="materia.id", index=True)
    id_alumno : int = Field(foreign_key="alumno.id", index=True)
    fecha_creacion: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    contenido : str
    satisfaccion : int = Field(ge=1, le=5)
    codigo : str = Field(index=True, unique=True)


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


# --- Modelos Pydantic (Respuesta de API) ---

class ProfesorPublic(BaseModel):
    nombre: str

class MateriaPublic(BaseModel):
    clave: str
    nombre: str
    creditos: int


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

class ResenaPendienteCreate(BaseModel):
    correo_alumno: str
    clave_materia: str
    nombre_profesor: str
    contenido: str
    satisfaccion: int = Field(ge=1, le=5)

class ResenaPendienteResponse(BaseModel):
    mensaje: str
    advertencia: str | None = None

class ResenaVerificadaResponse(BaseModel):
    mensaje: str
    status: str

class CarreraPublic(BaseModel):
    clave: str
    nombre: str

class RefreshRequest(BaseModel):
    ciclo: str = Field(description="Nombre del ciclo (ej: 2025A, 2025B)")
    centro: str = Field(description="Nombre del centro universitario")
    carrera: str = Field(description="Código de la carrera")
    materia: str = Field(description="Clave de la materia")

class RefreshResponse(BaseModel):
    mensaje: str
    status: str
    detalles: dict | None = None
    
class SoporteRequest(BaseModel):
    nombre: str
    tipo: str
    mensaje: str
    imagen: str | None = None 
    fecha: str
