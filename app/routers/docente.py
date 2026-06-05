"""
EscudoEscolar — Router del Docente
Carga de notas, asistencia, tareas, cuaderno, reuniones
"""

import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from database import get_db
from models.models import (
    Usuario, AsignacionDocente, Materia, Curso, InscripcionAlumno,
    CalificacionRegular, CuadernoNotificacion, Tarea, Asistencia,
    TipoNotificacionEnum, AsistenciaEstadoEnum, VinculoFamiliar,
)
from config import settings
from templating import templates
from services.notificaciones import despachar_notificacion

router = APIRouter(prefix="/docente", tags=["docente"])


def require_docente(request: Request) -> Usuario:
    user = getattr(request.state, "user", None)
    if not user or user.rol.value not in ("DOCENTE", "DIRECTIVO", "ADMIN"):
        raise Exception("No autorizado")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    # Mis asignaciones (cursos y materias que dicto)
    stmt = (
        select(AsignacionDocente)
        .where(AsignacionDocente.docente_id == docente.id)
        .options(
            selectinload(AsignacionDocente.materia),
            selectinload(AsignacionDocente.curso),
        )
    )
    result = await db.execute(stmt)
    asignaciones = result.scalars().all()

    # Alumnos en riesgo (promedio < 4) en mis materias
    alumnos_riesgo = []
    for asig in asignaciones:
        stmt_riesgo = (
            select(
                Usuario.nombre,
                func.avg(CalificacionRegular.nota).label("promedio"),
                InscripcionAlumno.alumno_id,
            )
            .join(InscripcionAlumno, InscripcionAlumno.alumno_id == Usuario.id)
            .join(CalificacionRegular, CalificacionRegular.inscripcion_id == InscripcionAlumno.id)
            .where(
                CalificacionRegular.asignacion_docente_id == asig.id,
                InscripcionAlumno.ciclo_lectivo == date.today().year,
            )
            .group_by(Usuario.id, InscripcionAlumno.alumno_id)
            .having(func.avg(CalificacionRegular.nota) < settings.NOTA_AMARILLA)
        )
        result_riesgo = await db.execute(stmt_riesgo)
        for row in result_riesgo:
            alumnos_riesgo.append({
                "nombre": row.nombre,
                "promedio": round(float(row.promedio), 2),
                "materia": asig.materia.nombre,
                "curso": asig.curso.nombre_completo,
                "alumno_id": row.alumno_id,
            })

    # Tareas próximas a vencer
    stmt_tareas = (
        select(Tarea)
        .join(AsignacionDocente)
        .where(
            AsignacionDocente.docente_id == docente.id,
            Tarea.fecha_entrega >= date.today(),
        )
        .options(
            selectinload(Tarea.asignacion_docente)
            .selectinload(AsignacionDocente.materia)
        )
        .order_by(Tarea.fecha_entrega.asc())
        .limit(5)
    )
    result_tareas = await db.execute(stmt_tareas)
    tareas_proximas = result_tareas.scalars().all()

    return templates.TemplateResponse(
             request,
        "docente/dashboard.html",
        {
            "docente": docente,
            "asignaciones": asignaciones,
            "alumnos_riesgo": alumnos_riesgo,
            "tareas_proximas": tareas_proximas,
            "success": success,
            "error": error,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE NOTAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/carga-notas", response_class=HTMLResponse)
async def carga_notas_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    asignacion_id: Optional[int] = None,
    trimestre: Optional[int] = None,
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    stmt = (
        select(AsignacionDocente)
        .where(AsignacionDocente.docente_id == docente.id)
        .options(
            selectinload(AsignacionDocente.materia),
            selectinload(AsignacionDocente.curso),
        )
    )
    result = await db.execute(stmt)
    asignaciones = result.scalars().all()

    alumnos_inscriptos = []
    notas_existentes = {}
    asignacion_sel = None

    if asignacion_id and trimestre:
        asignacion_sel = next((a for a in asignaciones if a.id == asignacion_id), None)
        if asignacion_sel:
            ciclo = date.today().year
            stmt_alumnos = (
                select(InscripcionAlumno)
                .where(
                    InscripcionAlumno.curso_id == asignacion_sel.curso_id,
                    InscripcionAlumno.ciclo_lectivo == ciclo,
                )
                .options(selectinload(InscripcionAlumno.alumno))
                .order_by(InscripcionAlumno.id)
            )
            result_alumnos = await db.execute(stmt_alumnos)
            alumnos_inscriptos = result_alumnos.scalars().all()

            # Notas ya cargadas
            stmt_notas = (
                select(CalificacionRegular)
                .where(
                    CalificacionRegular.asignacion_docente_id == asignacion_id,
                    CalificacionRegular.trimestre == trimestre,
                    CalificacionRegular.inscripcion_id.in_(
                        [a.id for a in alumnos_inscriptos]
                    ),
                )
            )
            result_notas = await db.execute(stmt_notas)
            for nota in result_notas.scalars().all():
                notas_existentes[nota.inscripcion_id] = float(nota.nota)

    return templates.TemplateResponse(
         request,
        "docente/carga_notas.html",
        {
            "docente": docente,
            "asignaciones": asignaciones,
            "asignacion_sel": asignacion_sel,
            "alumnos": alumnos_inscriptos,
            "notas_existentes": notas_existentes,
            "trimestre_sel": trimestre,
            "trimetres": [1, 2, 3],
            "success": success,
            "error": error,
        },
    )


@router.post("/carga-notas/manual")
async def carga_notas_manual(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    docente = require_docente(request)
    form = await request.form()

    asignacion_id = int(form.get("asignacion_id", 0))
    trimestre = int(form.get("trimestre", 1))

    # Verificar que la asignación pertenece al docente
    stmt = select(AsignacionDocente).where(
        AsignacionDocente.id == asignacion_id,
        AsignacionDocente.docente_id == docente.id,
    )
    result = await db.execute(stmt)
    asignacion = result.scalar_one_or_none()

    if not asignacion:
        return RedirectResponse(
            url="/docente/carga-notas?error=Asignación+no+encontrada",
            status_code=303,
        )

    notas_guardadas = 0
    alertas_generadas = 0

    for key, value in form.items():
        if key.startswith("nota_"):
            inscripcion_id = int(key.split("_")[1])
            try:
                nota_val = float(value.replace(",", "."))
                if not (1.0 <= nota_val <= 10.0):
                    continue

                # Upsert: actualizar si existe, crear si no
                stmt_existing = select(CalificacionRegular).where(
                    CalificacionRegular.inscripcion_id == inscripcion_id,
                    CalificacionRegular.asignacion_docente_id == asignacion_id,
                    CalificacionRegular.trimestre == trimestre,
                )
                result_ex = await db.execute(stmt_existing)
                cal_existing = result_ex.scalar_one_or_none()

                if cal_existing:
                    cal_existing.nota = nota_val
                else:
                    nueva_cal = CalificacionRegular(
                        inscripcion_id=inscripcion_id,
                        asignacion_docente_id=asignacion_id,
                        trimestre=trimestre,
                        nota=nota_val,
                    )
                    db.add(nueva_cal)

                notas_guardadas += 1

                # Generar alerta si nota < 4
                if nota_val < settings.NOTA_AMARILLA:
                    alertas_generadas += 1
                    stmt_inscr = (
                        select(InscripcionAlumno)
                        .where(InscripcionAlumno.id == inscripcion_id)
                        .options(selectinload(InscripcionAlumno.alumno))
                    )
                    result_inscr = await db.execute(stmt_inscr)
                    inscripcion = result_inscr.scalar_one_or_none()

                    if inscripcion:
                        # Notificar tutores
                        stmt_tutores = (
                            select(VinculoFamiliar)
                            .where(VinculoFamiliar.alumno_id == inscripcion.alumno_id)
                            .options(selectinload(VinculoFamiliar.tutor))
                        )
                        result_tutores = await db.execute(stmt_tutores)
                        vinculos = result_tutores.scalars().all()

                        for vinculo in vinculos:
                            notif = CuadernoNotificacion(
                                emisor_id=docente.id,
                                receptor_id=vinculo.tutor_id,
                                tipo_notificacion=TipoNotificacionEnum.ALERTA_ACADEMICA,
                                titulo=f"Alerta Académica: {inscripcion.alumno.nombre}",
                                contenido=(
                                    f"Se registró una calificación de {nota_val} "
                                    f"en {asignacion.materia.nombre}, "
                                    f"Trimestre {trimestre}."
                                ),
                                requiere_firma=False,
                            )
                            db.add(notif)
                            background_tasks.add_task(
                                despachar_notificacion,
                                email_destinatario=vinculo.tutor.email,
                                nombre_destinatario=vinculo.tutor.nombre,
                                telefono=vinculo.tutor.telefono,
                                titulo=notif.titulo,
                                contenido=notif.contenido,
                                tipo="ALERTA_ACADEMICA",
                            )

            except (ValueError, TypeError):
                continue

    await db.commit()

    msg = f"{notas_guardadas}+nota/s+guardadas"
    if alertas_generadas:
        msg += f",+{alertas_generadas}+alerta/s+enviadas+a+familias"

    return RedirectResponse(
        url=f"/docente/carga-notas?asignacion_id={asignacion_id}&trimestre={trimestre}&success={msg}",
        status_code=303,
    )


@router.post("/carga-notas/csv")
async def carga_notas_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    asignacion_id: int = Form(...),
    trimestre: int = Form(...),
    archivo: UploadFile = File(...),
):
    docente = require_docente(request)

    stmt = select(AsignacionDocente).where(
        AsignacionDocente.id == asignacion_id,
        AsignacionDocente.docente_id == docente.id,
    )
    result = await db.execute(stmt)
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        return RedirectResponse(url="/docente/carga-notas?error=Asignación+no+válida", status_code=303)

    contenido = await archivo.read()
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")

    reader = csv.DictReader(io.StringIO(texto))
    procesados = 0
    errores = []

    for row in reader:
        email = row.get("email", "").strip().lower()
        nota_str = row.get("nota", "").strip().replace(",", ".")
        if not email or not nota_str:
            continue

        try:
            nota_val = float(nota_str)
            if not (1.0 <= nota_val <= 10.0):
                errores.append(f"{email}: nota fuera de rango ({nota_val})")
                continue

            # Buscar alumno por email
            stmt_u = select(Usuario).where(Usuario.email == email)
            result_u = await db.execute(stmt_u)
            usuario = result_u.scalar_one_or_none()
            if not usuario:
                errores.append(f"{email}: usuario no encontrado")
                continue

            stmt_inscr = select(InscripcionAlumno).where(
                InscripcionAlumno.alumno_id == usuario.id,
                InscripcionAlumno.curso_id == asignacion.curso_id,
                InscripcionAlumno.ciclo_lectivo == date.today().year,
            )
            result_inscr = await db.execute(stmt_inscr)
            inscripcion = result_inscr.scalar_one_or_none()
            if not inscripcion:
                errores.append(f"{email}: no inscripto en el curso")
                continue

            stmt_ex = select(CalificacionRegular).where(
                CalificacionRegular.inscripcion_id == inscripcion.id,
                CalificacionRegular.asignacion_docente_id == asignacion_id,
                CalificacionRegular.trimestre == trimestre,
            )
            result_ex = await db.execute(stmt_ex)
            cal_ex = result_ex.scalar_one_or_none()

            if cal_ex:
                cal_ex.nota = nota_val
            else:
                db.add(CalificacionRegular(
                    inscripcion_id=inscripcion.id,
                    asignacion_docente_id=asignacion_id,
                    trimestre=trimestre,
                    nota=nota_val,
                ))
            procesados += 1

        except ValueError:
            errores.append(f"{email}: nota inválida ({nota_str})")

    await db.commit()

    msg = f"{procesados}+notas+importadas+por+CSV"
    if errores:
        msg += f".+{len(errores)}+errores+omitidos"
    return RedirectResponse(url=f"/docente/carga-notas?success={msg}", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# ASISTENCIA
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/asistencia", response_class=HTMLResponse)
async def asistencia_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    curso_id: Optional[int] = None,
    fecha_str: Optional[str] = None,
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    # Cursos del docente
    stmt = (
        select(AsignacionDocente.curso_id, Curso.division, Curso.turno)
        .join(Curso)
        .where(AsignacionDocente.docente_id == docente.id)
        .distinct()
    )
    result = await db.execute(stmt)
    cursos_raw = result.all()
    cursos = [{"id": r[0], "nombre": f"{r[1]} ({r[2].value})"} for r in cursos_raw]

    alumnos = []
    asistencias_hoy = {}
    fecha_sel = date.today()

    if fecha_str:
        try:
            fecha_sel = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    if curso_id:
        stmt_alumnos = (
            select(InscripcionAlumno)
            .where(
                InscripcionAlumno.curso_id == curso_id,
                InscripcionAlumno.ciclo_lectivo == date.today().year,
            )
            .options(selectinload(InscripcionAlumno.alumno))
            .order_by(InscripcionAlumno.id)
        )
        result_alumnos = await db.execute(stmt_alumnos)
        alumnos = result_alumnos.scalars().all()

        for a in alumnos:
            stmt_asist = select(Asistencia).where(
                Asistencia.inscripcion_id == a.id,
                Asistencia.fecha == fecha_sel,
            )
            result_asist = await db.execute(stmt_asist)
            asist = result_asist.scalar_one_or_none()
            asistencias_hoy[a.id] = asist.estado.value if asist else "PRESENTE"

    return templates.TemplateResponse(
             request,
        "docente/asistencia.html",
        {
            "docente": docente,
            "cursos": cursos,
            "curso_id_sel": curso_id,
            "alumnos": alumnos,
            "asistencias": asistencias_hoy,
            "fecha_sel": fecha_sel,
            "estados_asistencia": [e.value for e in AsistenciaEstadoEnum],
            "success": success,
            "error": error,
        },
    )


@router.post("/asistencia")
async def asistencia_submit(request: Request, db: AsyncSession = Depends(get_db)):
    docente = require_docente(request)
    form = await request.form()

    curso_id = int(form.get("curso_id", 0))
    fecha_str = form.get("fecha", str(date.today()))
    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        fecha = date.today()

    VALORES_FALTA = {
        "PRESENTE": 0.00,
        "AUSENTE_JUSTIFICADO": 0.00,
        "AUSENTE_INJUSTIFICADO": 1.00,
        "MEDIA_FALTA": 0.50,
    }

    stmt_alumnos = select(InscripcionAlumno).where(
        InscripcionAlumno.curso_id == curso_id,
        InscripcionAlumno.ciclo_lectivo == date.today().year,
    )
    result = await db.execute(stmt_alumnos)
    inscripciones = result.scalars().all()

    for inscripcion in inscripciones:
        estado_str = form.get(f"asist_{inscripcion.id}", "PRESENTE")
        try:
            estado_enum = AsistenciaEstadoEnum(estado_str)
        except ValueError:
            estado_enum = AsistenciaEstadoEnum.PRESENTE

        stmt_ex = select(Asistencia).where(
            Asistencia.inscripcion_id == inscripcion.id,
            Asistencia.fecha == fecha,
        )
        result_ex = await db.execute(stmt_ex)
        asist_ex = result_ex.scalar_one_or_none()

        if asist_ex:
            asist_ex.estado = estado_enum
            asist_ex.valor_falta = VALORES_FALTA[estado_str]
        else:
            db.add(Asistencia(
                inscripcion_id=inscripcion.id,
                fecha=fecha,
                estado=estado_enum,
                valor_falta=VALORES_FALTA[estado_str],
            ))

    await db.commit()
    return RedirectResponse(
        url=f"/docente/asistencia?curso_id={curso_id}&fecha_str={fecha_str}&success=Asistencia+guardada",
        status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TAREAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tareas", response_class=HTMLResponse)
async def tareas_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    stmt_asig = (
        select(AsignacionDocente)
        .where(AsignacionDocente.docente_id == docente.id)
        .options(
            selectinload(AsignacionDocente.materia),
            selectinload(AsignacionDocente.curso),
        )
    )
    result = await db.execute(stmt_asig)
    asignaciones = result.scalars().all()

    stmt_tareas = (
        select(Tarea)
        .join(AsignacionDocente)
        .where(AsignacionDocente.docente_id == docente.id)
        .options(
            selectinload(Tarea.asignacion_docente)
            .selectinload(AsignacionDocente.materia),
            selectinload(Tarea.asignacion_docente)
            .selectinload(AsignacionDocente.curso),
        )
        .order_by(Tarea.fecha_entrega.desc())
    )
    result_tareas = await db.execute(stmt_tareas)
    tareas = result_tareas.scalars().all()

    return templates.TemplateResponse(
            request,
        "docente/tareas.html",
        {
            "docente": docente,
            "asignaciones": asignaciones,
            "tareas": tareas,
            "hoy": date.today(),
            "success": success,
            "error": error,
        },
    )


@router.post("/tareas/nueva")
async def tarea_nueva(
    request: Request,
    db: AsyncSession = Depends(get_db),
    asignacion_id: int = Form(...),
    titulo: str = Form(...),
    descripcion: str = Form(...),
    fecha_entrega: str = Form(...),
):
    docente = require_docente(request)

    # Verificar ownership
    stmt = select(AsignacionDocente).where(
        AsignacionDocente.id == asignacion_id,
        AsignacionDocente.docente_id == docente.id,
    )
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        return RedirectResponse(url="/docente/tareas?error=Asignación+inválida", status_code=303)

    try:
        fecha = datetime.strptime(fecha_entrega, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url="/docente/tareas?error=Fecha+inválida", status_code=303)

    tarea = Tarea(
        asignacion_docente_id=asignacion_id,
        titulo=titulo.strip(),
        descripcion=descripcion.strip(),
        fecha_entrega=fecha,
    )
    db.add(tarea)
    await db.commit()
    return RedirectResponse(url="/docente/tareas?success=Tarea+creada+correctamente", status_code=303)


@router.post("/tareas/eliminar/{tarea_id}")
async def tarea_eliminar(
    tarea_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    docente = require_docente(request)
    stmt = (
        select(Tarea)
        .join(AsignacionDocente)
        .where(
            Tarea.id == tarea_id,
            AsignacionDocente.docente_id == docente.id,
        )
    )
    result = await db.execute(stmt)
    tarea = result.scalar_one_or_none()
    if tarea:
        await db.delete(tarea)
        await db.commit()
    return RedirectResponse(url="/docente/tareas?success=Tarea+eliminada", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# CUADERNO / COMUNICACIONES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cuaderno", response_class=HTMLResponse)
async def cuaderno_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    stmt = (
        select(CuadernoNotificacion)
        .where(
            or_(
                CuadernoNotificacion.emisor_id == docente.id,
                CuadernoNotificacion.receptor_id == docente.id,
            )
        )
        .options(
            selectinload(CuadernoNotificacion.receptor),
            selectinload(CuadernoNotificacion.emisor),
        )
        .order_by(CuadernoNotificacion.fecha_envio.desc())
    )
    result = await db.execute(stmt)
    notificaciones = result.scalars().all()

    # Alumnos del docente para el formulario
    stmt_alumnos = (
        select(Usuario, InscripcionAlumno)
        .join(InscripcionAlumno, InscripcionAlumno.alumno_id == Usuario.id)
        .join(AsignacionDocente, AsignacionDocente.curso_id == InscripcionAlumno.curso_id)
        .where(
            AsignacionDocente.docente_id == docente.id,
            InscripcionAlumno.ciclo_lectivo == date.today().year,
        )
        .distinct()
    )
    result_alumnos = await db.execute(stmt_alumnos)
    alumnos = [row[0] for row in result_alumnos.all()]

    return templates.TemplateResponse(
            request,
        "docente/cuaderno.html",
        {
            "docente": docente,
            "notificaciones": notificaciones,
            "alumnos": alumnos,
            "tipos": [t.value for t in TipoNotificacionEnum],
            "success": success,
            "error": error,
        },
    )


@router.post("/cuaderno/enviar")
async def cuaderno_enviar(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    receptor_id: int = Form(...),
    tipo: str = Form(...),
    titulo: str = Form(...),
    contenido: str = Form(...),
    requiere_firma: bool = Form(default=False),
):
    docente = require_docente(request)

    # Buscar receptor
    stmt = select(Usuario).where(Usuario.id == receptor_id)
    result = await db.execute(stmt)
    receptor = result.scalar_one_or_none()
    if not receptor:
        return RedirectResponse(url="/docente/cuaderno?error=Destinatario+no+encontrado", status_code=303)

    notif = CuadernoNotificacion(
        emisor_id=docente.id,
        receptor_id=receptor_id,
        tipo_notificacion=TipoNotificacionEnum(tipo),
        titulo=titulo.strip(),
        contenido=contenido.strip(),
        requiere_firma=requiere_firma,
    )
    db.add(notif)
    await db.flush()

    background_tasks.add_task(
        despachar_notificacion,
        email_destinatario=receptor.email,
        nombre_destinatario=receptor.nombre,
        telefono=receptor.telefono,
        titulo=titulo,
        contenido=contenido,
        tipo=tipo,
        requiere_firma=requiere_firma,
        url_firma=f"https://escudoescolar.edu.ar/tutor/cuaderno",
    )

    await db.commit()
    return RedirectResponse(url="/docente/cuaderno?success=Notificación+enviada", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# REUNIONES (solicitudes de familias)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reuniones", response_class=HTMLResponse)
async def reuniones_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    docente = require_docente(request)

    stmt = (
        select(CuadernoNotificacion)
        .where(
            CuadernoNotificacion.receptor_id == docente.id,
            CuadernoNotificacion.titulo.contains("Reunión"),
        )
        .options(selectinload(CuadernoNotificacion.emisor))
        .order_by(CuadernoNotificacion.fecha_envio.desc())
    )
    result = await db.execute(stmt)
    solicitudes = result.scalars().all()

    return templates.TemplateResponse(
             request,
        "docente/reuniones.html",
        {
            "docente": docente,
            "solicitudes": solicitudes,
            "success": success,
            "error": error,
        },
    )