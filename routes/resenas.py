from lifespan import app
from models import *
from database import SessionDep
from dependencies import *
from fastapi import Query, Request
from fastapi.responses import HTMLResponse
import hashlib
import random
from email_service import enviar_enlace_verificacion
from faker import Faker
fake = Faker('es_MX')

@app.get("/resenas/", response_model=list[ResenaPublic])
def read_resenas(
        session: SessionDep,
        profesor: ProfesorOptDep = None,
        materia: MateriaOptDep = None,
        offset: int = 0,
        limit: Annotated[int, Query(le=100)] = 100):
    stmt = select(Resena)
    if profesor is not None:
        stmt = stmt.where(Resena.id_profesor == profesor)
    if materia is not None:
        stmt = stmt.where(Resena.id_materia == materia)
    resenas = session.exec(stmt.offset(offset).limit(limit)).all()

    result: list[ResenaPublic] = []
    for r in resenas:
        fake.seed_instance(hashlib.sha256((r.alumno.correo + str(r.alumno.id)).encode('utf-8')).hexdigest())
        result.append(ResenaPublic(
            profesor=r.profesor.nombre,
            materia=r.materia.clave,
            alumno= f"{fake.word()} {fake.color_name()}".title(),
            contenido=r.contenido,
            satisfaccion=r.satisfaccion
        ))
    return result


@app.post("/resenas/solicitar", response_model=ResenaPendienteResponse)
async def solicitar_resena(
    datos: ResenaPendienteCreate,
    session: SessionDep,
    request: Request
):

    id_alumno = validar_alumno(session, datos.correo_alumno)
    id_materia = validar_materia(session, datos.clave_materia)
    id_profesor = validar_profesor(session, datos.nombre_profesor)

    resena_existente = session.exec(
        select(Resena).where(
            Resena.id_profesor == id_profesor,
            Resena.id_materia == id_materia,
            Resena.id_alumno == id_alumno
        )
    ).first()

    # Verificar si ya existe una reseña pendiente
    pendiente_existente = session.exec(
        select(ResenaPendiente).where(
            ResenaPendiente.id_profesor == id_profesor,
            ResenaPendiente.id_materia == id_materia,
            ResenaPendiente.id_alumno == id_alumno
        )
    ).first()
    # Generar un código único de 6 dígitos, valida en la db si ya existe, si ya crea uno nuevo
    while True:
        codigo = str(random.randint(0, 999999)).zfill(6)

        codigo_existente = session.exec(
            select(ResenaPendiente).where(ResenaPendiente.codigo == codigo)
        ).first()
        if not codigo_existente:
            break

    if pendiente_existente:

        pendiente_existente.contenido = datos.contenido
        pendiente_existente.satisfaccion = datos.satisfaccion
        pendiente_existente.codigo = codigo
        pendiente_existente.fecha_creacion = datetime.datetime.now(
            datetime.timezone.utc)
        session.commit()
    else:

        nueva_pendiente = ResenaPendiente(
            id_profesor=id_profesor,
            id_materia=id_materia,
            id_alumno=id_alumno,
            contenido=datos.contenido,
            satisfaccion=datos.satisfaccion,
            codigo=codigo
        )
        print(
            f"DEBUG: profesor:{id_profesor}, materia:{id_materia}, alumno:{id_alumno}")
        print(
            f"DEBUG: Tipo de datos: {type(id_profesor)}, {type(id_materia)}, {type(id_alumno)}")
        session.add(nueva_pendiente)
        session.commit()

    try:

        # TAG: Ajustar URL base para producción
        base_url = "http://localhost:8080/api" or str(
            request.base_url).rstrip('/')+"/api"

        print(f"DEBUG: base_url para email: {base_url}")
        fake.seed_instance(hashlib.sha256((datos.correo_alumno + str(id_alumno)).encode('utf-8')).hexdigest())
        nombre=f"{fake.word()} {fake.color_name()}".title()
        
        await enviar_enlace_verificacion(datos.correo_alumno, codigo, nombre,base_url)

    except Exception as e:

        return ResenaPendienteResponse(
            mensaje="Reseña guardada, pero hubo un error al enviar el correo de verificación",
            advertencia=f"Error: {str(e)}"
        )
    tipo_accion = "actualizar" if resena_existente else "publicar"
    return ResenaPendienteResponse(
        mensaje=f"Proceso iniciado. Revisa tu correo ({datos.correo_alumno}) para verificar y {tipo_accion}."
    )


@app.get("/resenas/verificar/{codigo}", response_model=ResenaVerificadaResponse)
async def verificar_resena(
    codigo: str,
    session: SessionDep,
    json: bool = Query(False)
):
    pendiente = session.exec(
        select(ResenaPendiente).where(ResenaPendiente.codigo == codigo)
    ).first()

    if not pendiente:
        if json:
            raise HTTPException(
                status_code=404,
                detail="El enlace de verificación no es válido o ya fue utilizado."
            )

        return HTMLResponse("""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h2 style="color: #dc2626;">Codigo inválido</h2>
                <p>El enlace de verificación no es válido o ya fue utilizado.</p>
            </body>
        </html>
        """)

    try:

        resena_existente = session.exec(
            select(Resena).where(
                Resena.id_profesor == pendiente.id_profesor,
                Resena.id_materia == pendiente.id_materia,
                Resena.id_alumno == pendiente.id_alumno
            )
        ).first()

        if resena_existente:
            resena_existente.contenido = pendiente.contenido
            resena_existente.satisfaccion = pendiente.satisfaccion

            resena_existente.fecha_creacion = datetime.datetime.now(
                datetime.timezone.utc)
            session.add(resena_existente) 
        else:
            resena_publica = Resena(
                id_profesor=int(pendiente.id_profesor),
                id_materia=int(pendiente.id_materia),
                id_alumno=int(pendiente.id_alumno),
                contenido=pendiente.contenido,
                satisfaccion=pendiente.satisfaccion
            )
            session.add(resena_publica) # Marca para INSERT

        session.delete(pendiente)
        session.commit()

        if json:
            return ResenaVerificadaResponse(
                mensaje="Reseña publicada exitosamente",
                status="success"
            )

        return HTMLResponse("""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h1 style="color: #16a34a;">Acción completada.</h1>
                <p>Tu reseña ha sido verificada y publicada correctamente.</p>
            </body>
        </html>
        """)
        
    except Exception as e:
        session.rollback()
        print(f"ERROR al verificar reseña: {str(e)}")
        if json:
            raise HTTPException(
                status_code=500,
                detail=f"OCURRIO UN ERROR AL PROCESAR LA SOLICITUD"
            )
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center;">
                <h2 style="color: #dc2626;">Error</h2>
                <p>Ocurrió un error interno al procesar tu solicitud.</p>
            </body>
        </html>
        """)