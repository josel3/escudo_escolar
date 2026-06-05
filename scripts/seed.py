"""
Carga datos de demostración en EscudoEscolar.
Uso: python scripts/seed.py
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.database import AsyncSessionLocal, engine, init_db
from app.security import hash_password
from app.models.models import (
    Usuario, RolEnum, Curso, NivelEnum, TurnoEnum, Materia,
    AsignacionDocente, InscripcionAlumno, VinculoFamiliar,
    CalificacionRegular, CuadernoNotificacion, TipoNotificacionEnum,
    Tarea, Asistencia, AsistenciaEstadoEnum, LegajoPermanenteDocumento,
)

DEMO_PASS = "escudo123"
CICLO = date.today().year


async def upsert_user(session, email, nombre, rol, telefono=None):
    stmt = select(Usuario).where(Usuario.email == email)
    u = (await session.execute(stmt)).scalar_one_or_none()
    if u:
        return u
    u = Usuario(
        email=email,
        nombre=nombre,
        rol=rol,
        password_hash=hash_password(DEMO_PASS),
        telefono=telefono,
        activo=True,
    )
    session.add(u)
    await session.flush()
    return u


async def main():
    print("Inicializando tablas...")
    try:
        await init_db()
    except Exception as e:
        print("\n[ERROR] No se pudo conectar a MySQL.")
        print("  1. Iniciá Docker Desktop y ejecutá: docker compose up -d")
        print("  2. O configurá un servidor MySQL local en .env")
        print(f"  Detalle: {e}\n")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        admin = await upsert_user(session, "admin@escudoescolar.ar", "Admin Sistema", RolEnum.ADMIN)
        directivo = await upsert_user(
            session, "directivo@escudoescolar.ar", "María Directiva", RolEnum.DIRECTIVO, "5491112345678"
        )
        docente = await upsert_user(
            session, "docente@escudoescolar.ar", "Carlos Docente", RolEnum.DOCENTE, "5491198765432"
        )
        tutor = await upsert_user(
            session, "tutor@escudoescolar.ar", "Ana Familia", RolEnum.TUTOR, "5491155554444"
        )
        alumno = await upsert_user(
            session, "alumno@escudoescolar.ar", "Lucas Alumno", RolEnum.ALUMNO
        )

        stmt = select(Curso).where(Curso.division == "4to A")
        curso = (await session.execute(stmt)).scalar_one_or_none()
        if not curso:
            curso = Curso(
                anio=str(CICLO),
                nivel=NivelEnum.SECUNDARIO,
                division="4to A",
                turno=TurnoEnum.MANANA,
            )
            session.add(curso)
            await session.flush()

        materias_data = [
            ("MAT01", "Matemática"),
            ("LEN01", "Lengua y Literatura"),
            ("SOC01", "Ciencias Sociales"),
        ]
        materias = []
        for cod, nom in materias_data:
            stmt = select(Materia).where(Materia.codigo == cod)
            m = (await session.execute(stmt)).scalar_one_or_none()
            if not m:
                m = Materia(codigo=cod, nombre=nom)
                session.add(m)
                await session.flush()
            materias.append(m)

        asignaciones = []
        for m in materias:
            stmt = select(AsignacionDocente).where(
                AsignacionDocente.docente_id == docente.id,
                AsignacionDocente.materia_id == m.id,
                AsignacionDocente.curso_id == curso.id,
            )
            a = (await session.execute(stmt)).scalar_one_or_none()
            if not a:
                a = AsignacionDocente(docente_id=docente.id, materia_id=m.id, curso_id=curso.id)
                session.add(a)
                await session.flush()
            asignaciones.append(a)

        stmt = select(InscripcionAlumno).where(
            InscripcionAlumno.alumno_id == alumno.id,
            InscripcionAlumno.ciclo_lectivo == CICLO,
        )
        inscr = (await session.execute(stmt)).scalar_one_or_none()
        if not inscr:
            inscr = InscripcionAlumno(
                alumno_id=alumno.id,
                curso_id=curso.id,
                ciclo_lectivo=CICLO,
            )
            session.add(inscr)
            await session.flush()

        stmt = select(VinculoFamiliar).where(
            VinculoFamiliar.alumno_id == alumno.id,
            VinculoFamiliar.tutor_id == tutor.id,
        )
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(VinculoFamiliar(alumno_id=alumno.id, tutor_id=tutor.id, parentesco="Madre"))

        notas_demo = [(asignaciones[0], 8.5), (asignaciones[1], 5.5), (asignaciones[2], 3.5)]
        for asig, nota in notas_demo:
            stmt = select(CalificacionRegular).where(
                CalificacionRegular.inscripcion_id == inscr.id,
                CalificacionRegular.asignacion_docente_id == asig.id,
                CalificacionRegular.trimestre == 1,
            )
            if not (await session.execute(stmt)).scalar_one_or_none():
                session.add(
                    CalificacionRegular(
                        inscripcion_id=inscr.id,
                        asignacion_docente_id=asig.id,
                        trimestre=1,
                        nota=nota,
                    )
                )

        for i in range(5):
            f = date.today() - timedelta(days=i)
            stmt = select(Asistencia).where(Asistencia.inscripcion_id == inscr.id, Asistencia.fecha == f)
            if not (await session.execute(stmt)).scalar_one_or_none():
                session.add(
                    Asistencia(
                        inscripcion_id=inscr.id,
                        fecha=f,
                        estado=AsistenciaEstadoEnum.PRESENTE if i else AsistenciaEstadoEnum.AUSENTE_INJUSTIFICADO,
                        valor_falta=0.0 if i else 1.0,
                    )
                )

        stmt = select(Tarea).where(Tarea.titulo == "Trabajo práctico: Ecuaciones")
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                Tarea(
                    asignacion_docente_id=asignaciones[0].id,
                    titulo="Trabajo práctico: Ecuaciones",
                    descripcion="Resolver ejercicios 1 a 10 del capítulo 3.",
                    fecha_entrega=date.today() + timedelta(days=7),
                )
            )

        stmt = select(LegajoPermanenteDocumento).where(
            LegajoPermanenteDocumento.alumno_id == alumno.id,
            LegajoPermanenteDocumento.tipo_documento == "Fotocopia DNI",
        )
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                LegajoPermanenteDocumento(
                    alumno_id=alumno.id,
                    tipo_documento="Fotocopia DNI",
                    entregado=True,
                )
            )

        stmt = select(CuadernoNotificacion).where(
            CuadernoNotificacion.titulo == "Bienvenida al ciclo lectivo"
        )
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                CuadernoNotificacion(
                    emisor_id=directivo.id,
                    receptor_id=tutor.id,
                    tipo_notificacion=TipoNotificacionEnum.COMUNICADO,
                    titulo="Bienvenida al ciclo lectivo",
                    contenido="Les damos la bienvenida a EscudoEscolar. Revisen el cuaderno digital.",
                    requiere_firma=True,
                )
            )
            session.add(
                CuadernoNotificacion(
                    emisor_id=docente.id,
                    receptor_id=tutor.id,
                    tipo_notificacion=TipoNotificacionEnum.ALERTA_ACADEMICA,
                    titulo="Alerta: Lucas — Ciencias Sociales",
                    contenido="Se registró calificación 3.5 en el primer trimestre.",
                )
            )

        await session.commit()

    print("\n[OK] Datos de demo cargados.")
    print(f"  Contraseña para todos: {DEMO_PASS}")
    print("  admin@escudoescolar.ar      -> /admin/dashboard")
    print("  directivo@escudoescolar.ar  -> /directivo/dashboard")
    print("  docente@escudoescolar.ar    -> /docente/dashboard")
    print("  tutor@escudoescolar.ar      -> /tutor/dashboard")
    print("  alumno@escudoescolar.ar     -> /alumno/dashboard")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
