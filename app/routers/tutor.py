"""
EscudoEscolar — Router del Tutor / Familia
Dashboard familiar, cuaderno, firma, reuniones
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.templating import templates
from app.database import get_db
from app.models.models import (
    Usuario, VinculoFamiliar, InscripcionAlumno, CalificacionRegular,
    CuadernoNotificacion, Asistencia, AsignacionDocente, Materia,
)
from app.config import settings

router = APIRouter(prefix="/tutor", tags=["tutor"])


def require_tutor(request: Request) -> Usuario:
    user = getattr(request.state, "user", None)
    if not user or user.rol.value not in ("TUTOR", "ADMIN"):
        raise Exception("No autorizado")
    return user


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    alumno_id: Optional[int] = None,
    success: str = "",
    error: str = "",
):
    tutor = require_tutor(request)

    # Alumnos bajo tutela
    stmt = (
        select(VinculoFamiliar)
        .where(VinculoFamiliar.tutor_id == tutor.id)
        .options(selectinload(VinculoFamiliar.alumno))
    )
    result = await db.execute(stmt)
    vinculos = result.scalars().all()
    alumnos = [v.alumno for v in vinculos]

    if not alumnos:
        return templates.TemplateResponse(
            "tutor/dashboard.html",
            {"request": request, "tutor": tutor, "alumnos": [], "alumno_sel": None},
        )

    # Alumno seleccionado (por defecto el primero)
    alumno_sel_id = alumno_id or alumnos[0].id
    alumno_sel = next((a for a in alumnos if a.id == alumno_sel_id), alumnos[0])

    ciclo = date.today().year
    stmt_inscr = (
        select(InscripcionAlumno)
        .where(
            InscripcionAlumno.alumno_id == alumno_sel.id,
            InscripcionAlumno.ciclo_lectivo == ciclo,
        )
        .options(selectinload(InscripcionAlumno.curso))
    )
    result_inscr = await db.execute(stmt_inscr)
    inscripcion = result_inscr.scalar_one_or_none()

    materias_resumen = []
    total_faltas = 0.0
    porcentaje_asistencia = 100.0

    if inscripcion:
        stmt_notas = (
            select(CalificacionRegular)
            .where(CalificacionRegular.inscripcion_id == inscripcion.id)
            .options(
                selectinload(CalificacionRegular.asignacion_docente)
                .selectinload(AsignacionDocente.materia)
            )
        )
        result_notas = await db.execute(stmt_notas)
        cals = result_notas.scalars().all()

        por_materia: dict = {}
        for cal in cals:
            m = cal.asignacion_docente.materia
            if m.id not in por_materia:
                por_materia[m.id] = {"nombre": m.nombre, "notas": []}
            por_materia[m.id]["notas"].append(float(cal.nota))

        for mid, datos in por_materia.items():
            promedio = sum(datos["notas"]) / len(datos["notas"])
            materias_resumen.append({
                "nombre": datos["nombre"],
                "promedio": round(promedio, 2),
                "css": settings.semaforo_css(promedio),
            })

        # Asistencia
        stmt_faltas = select(func.sum(Asistencia.valor_falta)).where(
            Asistencia.inscripcion_id == inscripcion.id
        )
        result_f = await db.execute(stmt_faltas)
        total_faltas = float(result_f.scalar() or 0)
        stmt_dias = select(func.count(Asistencia.id)).where(Asistencia.inscripcion_id == inscripcion.id)
        result_d = await db.execute(stmt_dias)
        total_dias = int(result_d.scalar() or 1)
        porcentaje_asistencia = round(
            ((total_dias - total_faltas) / total_dias * 100) if total_dias else 100, 1
        )

    # Notificaciones pendientes de firma
    stmt_pendientes = select(func.count(CuadernoNotificacion.id)).where(
        CuadernoNotificacion.receptor_id == tutor.id,
        CuadernoNotificacion.requiere_firma == True,
        CuadernoNotificacion.firmado == False,
    )
    result_pend = await db.execute(stmt_pendientes)
    firmas_pendientes = int(result_pend.scalar() or 0)

    return templates.TemplateResponse(
        "tutor/dashboard.html",
        {
            "request": request,
            "tutor": tutor,
            "alumnos": alumnos,
            "alumno_sel": alumno_sel,
            "inscripcion": inscripcion,
            "materias": sorted(materias_resumen, key=lambda x: x["nombre"]),
            "total_faltas": total_faltas,
            "porcentaje_asistencia": porcentaje_asistencia,
            "firmas_pendientes": firmas_pendientes,
            "success": success,
            "error": error,
        },
    )


@router.get("/cuaderno", response_class=HTMLResponse)
async def cuaderno(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    tutor = require_tutor(request)

    stmt = (
        select(CuadernoNotificacion)
        .where(CuadernoNotificacion.receptor_id == tutor.id)
        .options(selectinload(CuadernoNotificacion.emisor))
        .order_by(CuadernoNotificacion.fecha_envio.desc())
    )
    result = await db.execute(stmt)
    notificaciones = result.scalars().all()

    return templates.TemplateResponse(
        "tutor/cuaderno.html",
        {
            "request": request,
            "tutor": tutor,
            "notificaciones": notificaciones,
            "success": success,
            "error": error,
        },
    )


@router.post("/cuaderno/firmar/{notif_id}")
async def firmar_cuaderno(
    notif_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tutor = require_tutor(request)

    stmt = select(CuadernoNotificacion).where(
        CuadernoNotificacion.id == notif_id,
        CuadernoNotificacion.receptor_id == tutor.id,
    )
    result = await db.execute(stmt)
    notif = result.scalar_one_or_none()

    if notif and not notif.firmado:
        notif.firmado = True
        notif.fecha_firma = datetime.utcnow()
        await db.commit()

    return RedirectResponse(
        url="/tutor/cuaderno?success=Notificación+firmada+correctamente",
        status_code=303,
    )


@router.get("/solicitar-reunion", response_class=HTMLResponse)
async def solicitar_reunion_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    tutor = require_tutor(request)

    stmt = (
        select(VinculoFamiliar)
        .where(VinculoFamiliar.tutor_id == tutor.id)
        .options(selectinload(VinculoFamiliar.alumno))
    )
    result = await db.execute(stmt)
    vinculos = result.scalars().all()

    # Docentes de los alumnos
    docentes_set = set()
    docentes = []
    for v in vinculos:
        stmt_d = (
            select(AsignacionDocente)
            .join(InscripcionAlumno, InscripcionAlumno.curso_id == AsignacionDocente.curso_id)
            .where(
                InscripcionAlumno.alumno_id == v.alumno_id,
                InscripcionAlumno.ciclo_lectivo == date.today().year,
            )
            .options(selectinload(AsignacionDocente.docente))
        )
        result_d = await db.execute(stmt_d)
        for asig in result_d.scalars().all():
            if asig.docente_id not in docentes_set:
                docentes_set.add(asig.docente_id)
                docentes.append(asig.docente)

    return templates.TemplateResponse(
        "tutor/solicitar_reunion.html",
        {
            "request": request,
            "tutor": tutor,
            "docentes": docentes,
            "success": success,
            "error": error,
        },
    )


@router.post("/solicitar-reunion")
async def solicitar_reunion_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    docente_id: int = Form(...),
    fecha_propuesta: str = Form(...),
    motivo: str = Form(...),
    modalidad: str = Form(default="presencial"),
):
    tutor = require_tutor(request)

    stmt = select(Usuario).where(Usuario.id == docente_id)
    result = await db.execute(stmt)
    docente = result.scalar_one_or_none()
    if not docente:
        return RedirectResponse(
            url="/tutor/solicitar-reunion?error=Docente+no+encontrado",
            status_code=303,
        )

    notif = CuadernoNotificacion(
        emisor_id=tutor.id,
        receptor_id=docente_id,
        tipo_notificacion="INFORME",
        titulo=f"Solicitud de Reunión — {modalidad.capitalize()}",
        contenido=(
            f"Familia {tutor.nombre} solicita una reunión.\n"
            f"Fecha propuesta: {fecha_propuesta}\n"
            f"Modalidad: {modalidad}\n\n"
            f"Motivo: {motivo}"
        ),
        requiere_firma=False,
    )
    db.add(notif)
    await db.commit()

    return RedirectResponse(
        url="/tutor/solicitar-reunion?success=Solicitud+enviada+al+docente",
        status_code=303,
    )