"""
EscudoEscolar — Router del Directivo
Estadísticas, legajo escolar, casos bullying, sanciones, comunicados
"""

import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Usuario, Curso, InscripcionAlumno, CalificacionRegular, Asistencia,
    CuadernoNotificacion, LegajoPermanenteDocumento, AnotacionEspecial,
    SancionDisciplinaria, AsignacionDocente, BoletinHistorico, VinculoFamiliar,
    TipoNotificacionEnum, CategoriaMedicaEnum, TipoSancionEnum, EstadoInscripcionEnum,
    RolEnum,
)
from app.config import settings
from app.templating import templates
from app.services.notificaciones import despachar_notificacion

router = APIRouter(prefix="/directivo", tags=["directivo"])


def require_directivo(request: Request) -> Usuario:
    user = getattr(request.state, "user", None)
    if not user or user.rol.value not in ("DIRECTIVO", "ADMIN"):
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
    directivo = require_directivo(request)
    ciclo = date.today().year

    # Total alumnos activos
    stmt_total = select(func.count(InscripcionAlumno.id)).where(
        InscripcionAlumno.ciclo_lectivo == ciclo
    )
    result = await db.execute(stmt_total)
    total_alumnos = int(result.scalar() or 0)

    # Alumnos en riesgo (al menos una materia < 4)
    stmt_riesgo = (
        select(func.count(InscripcionAlumno.alumno_id.distinct()))
        .join(CalificacionRegular)
        .where(
            InscripcionAlumno.ciclo_lectivo == ciclo,
            CalificacionRegular.nota < settings.NOTA_AMARILLA,
        )
    )
    result = await db.execute(stmt_riesgo)
    alumnos_riesgo = int(result.scalar() or 0)

    # Tasa de ausentismo (promedio de faltas/alumno)
    stmt_faltas = select(func.avg(Asistencia.valor_falta)).join(
        InscripcionAlumno
    ).where(InscripcionAlumno.ciclo_lectivo == ciclo)
    result = await db.execute(stmt_faltas)
    prom_faltas = float(result.scalar() or 0)

    # Alertas de bullying sin resolver
    stmt_bullying = select(func.count(CuadernoNotificacion.id)).where(
        CuadernoNotificacion.tipo_notificacion == TipoNotificacionEnum.INCIDENCIA_BULLYING,
        CuadernoNotificacion.receptor_id == directivo.id,
        CuadernoNotificacion.firmado == False,
    )
    result = await db.execute(stmt_bullying)
    alertas_bullying = int(result.scalar() or 0)

    # Firmas pendientes globales
    stmt_firmas = select(func.count(CuadernoNotificacion.id)).where(
        CuadernoNotificacion.emisor_id == directivo.id,
        CuadernoNotificacion.requiere_firma == True,
        CuadernoNotificacion.firmado == False,
    )
    result = await db.execute(stmt_firmas)
    firmas_pendientes = int(result.scalar() or 0)

    # Últimas incidencias de bullying
    stmt_incidencias = (
        select(CuadernoNotificacion)
        .where(
            CuadernoNotificacion.tipo_notificacion == TipoNotificacionEnum.INCIDENCIA_BULLYING,
            CuadernoNotificacion.receptor_id == directivo.id,
        )
        .options(selectinload(CuadernoNotificacion.emisor))
        .order_by(CuadernoNotificacion.fecha_envio.desc())
        .limit(5)
    )
    result_inc = await db.execute(stmt_incidencias)
    incidencias_recientes = result_inc.scalars().all()

    return templates.TemplateResponse(
        "directivo/dashboard.html",
        {
            "request": request,
            "directivo": directivo,
            "total_alumnos": total_alumnos,
            "alumnos_riesgo": alumnos_riesgo,
            "pct_riesgo": round((alumnos_riesgo / total_alumnos * 100) if total_alumnos else 0, 1),
            "prom_faltas": round(prom_faltas, 2),
            "alertas_bullying": alertas_bullying,
            "firmas_pendientes": firmas_pendientes,
            "incidencias_recientes": incidencias_recientes,
            "success": success,
            "error": error,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# ESTADÍSTICAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/estadisticas", response_class=HTMLResponse)
async def estadisticas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ciclo: Optional[int] = None,
):
    directivo = require_directivo(request)
    ciclo = ciclo or date.today().year

    # Distribución por semáforo global
    stmt_notas = select(CalificacionRegular.nota).join(InscripcionAlumno).where(
        InscripcionAlumno.ciclo_lectivo == ciclo
    )
    result = await db.execute(stmt_notas)
    todas_notas = [float(r[0]) for r in result.all()]

    verde = sum(1 for n in todas_notas if n >= settings.NOTA_VERDE)
    amarillo = sum(1 for n in todas_notas if settings.NOTA_AMARILLA <= n < settings.NOTA_VERDE)
    rojo = sum(1 for n in todas_notas if n < settings.NOTA_AMARILLA)
    total_notas = len(todas_notas) or 1
    promedio_general = round(sum(todas_notas) / total_notas, 2) if todas_notas else 0

    # Por curso
    stmt_cursos = (
        select(
            Curso.division,
            func.avg(CalificacionRegular.nota).label("promedio"),
            func.count(InscripcionAlumno.alumno_id.distinct()).label("cant_alumnos"),
        )
        .join(InscripcionAlumno, InscripcionAlumno.curso_id == Curso.id)
        .join(CalificacionRegular, CalificacionRegular.inscripcion_id == InscripcionAlumno.id)
        .where(InscripcionAlumno.ciclo_lectivo == ciclo)
        .group_by(Curso.id, Curso.division)
        .order_by(Curso.division)
    )
    result_cursos = await db.execute(stmt_cursos)
    stats_cursos = [
        {
            "division": r[0],
            "promedio": round(float(r[1]), 2),
            "cant_alumnos": r[2],
            "css": settings.semaforo_css(float(r[1])),
        }
        for r in result_cursos.all()
    ]

    # Asistencia por curso
    stmt_asist_cur = (
        select(
            Curso.division,
            func.sum(Asistencia.valor_falta).label("total_faltas"),
            func.count(Asistencia.id).label("total_dias"),
        )
        .join(InscripcionAlumno, InscripcionAlumno.curso_id == Curso.id)
        .join(Asistencia, Asistencia.inscripcion_id == InscripcionAlumno.id)
        .where(InscripcionAlumno.ciclo_lectivo == ciclo)
        .group_by(Curso.id, Curso.division)
    )
    result_asist = await db.execute(stmt_asist_cur)
    stats_asistencia = [
        {
            "division": r[0],
            "total_faltas": float(r[1] or 0),
            "total_dias": int(r[2] or 1),
            "pct_asistencia": round(
                (1 - float(r[1] or 0) / max(int(r[2] or 1), 1)) * 100, 1
            ),
        }
        for r in result_asist.all()
    ]

    return templates.TemplateResponse(
        "directivo/estadisticas.html",
        {
            "request": request,
            "directivo": directivo,
            "ciclo": ciclo,
            "verde": verde,
            "amarillo": amarillo,
            "rojo": rojo,
            "total_notas": total_notas,
            "promedio_general": promedio_general,
            "stats_cursos": stats_cursos,
            "stats_asistencia": stats_asistencia,
        },
    )


@router.get("/estadisticas/exportar-csv")
async def estadisticas_exportar_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ciclo: Optional[int] = None,
):
    require_directivo(request)
    ciclo = ciclo or date.today().year

    stmt = (
        select(
            Curso.division,
            func.avg(CalificacionRegular.nota).label("promedio"),
            func.count(InscripcionAlumno.alumno_id.distinct()).label("alumnos"),
        )
        .join(InscripcionAlumno, InscripcionAlumno.curso_id == Curso.id)
        .join(CalificacionRegular, CalificacionRegular.inscripcion_id == InscripcionAlumno.id)
        .where(InscripcionAlumno.ciclo_lectivo == ciclo)
        .group_by(Curso.id, Curso.division)
        .order_by(Curso.division)
    )
    result = await db.execute(stmt)
    filas = result.all()

    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Curso", "Promedio", "Cantidad alumnos", "Ciclo"])
    for r in filas:
        writer.writerow([r[0], round(float(r[1]), 2), r[2], ciclo])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=estadisticas_{ciclo}.csv"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# LEGAJO ESCOLAR DIGITAL
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/alumnos", response_class=HTMLResponse)
async def lista_alumnos(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str = "",
    ciclo: Optional[int] = None,
):
    directivo = require_directivo(request)
    ciclo = ciclo or date.today().year

    stmt = (
        select(Usuario)
        .join(InscripcionAlumno, InscripcionAlumno.alumno_id == Usuario.id)
        .where(
            Usuario.rol == RolEnum.ALUMNO,
            InscripcionAlumno.ciclo_lectivo == ciclo,
        )
        .options(selectinload(Usuario.inscripciones).selectinload(InscripcionAlumno.curso))
        .order_by(Usuario.nombre)
    )
    if q:
        stmt = stmt.where(Usuario.nombre.contains(q))

    result = await db.execute(stmt)
    alumnos = result.scalars().unique().all()

    return templates.TemplateResponse(
        "directivo/alumnos.html",
        {
            "request": request,
            "directivo": directivo,
            "alumnos": alumnos,
            "ciclo": ciclo,
            "q": q,
        },
    )


@router.get("/legajos/{alumno_id}", response_class=HTMLResponse)
async def legajo_alumno(
    alumno_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    directivo = require_directivo(request)

    stmt = select(Usuario).where(Usuario.id == alumno_id)
    result = await db.execute(stmt)
    alumno = result.scalar_one_or_none()
    if not alumno:
        return RedirectResponse(url="/directivo/alumnos?error=Alumno+no+encontrado", status_code=303)

    # Documentos del legajo
    stmt_docs = select(LegajoPermanenteDocumento).where(
        LegajoPermanenteDocumento.alumno_id == alumno_id
    )
    result_docs = await db.execute(stmt_docs)
    documentos = result_docs.scalars().all()

    # Anotaciones especiales
    stmt_anot = (
        select(AnotacionEspecial)
        .where(AnotacionEspecial.alumno_id == alumno_id)
        .order_by(AnotacionEspecial.fecha_registro.desc())
    )
    result_anot = await db.execute(stmt_anot)
    anotaciones = result_anot.scalars().all()

    # Sanciones
    stmt_sanc = (
        select(SancionDisciplinaria)
        .join(InscripcionAlumno)
        .where(InscripcionAlumno.alumno_id == alumno_id)
        .options(selectinload(SancionDisciplinaria.inscripcion).selectinload(InscripcionAlumno.curso))
        .order_by(SancionDisciplinaria.fecha_sancion.desc())
    )
    result_sanc = await db.execute(stmt_sanc)
    sanciones = result_sanc.scalars().all()

    # Historial académico completo (boletines)
    stmt_bol = (
        select(BoletinHistorico)
        .where(BoletinHistorico.alumno_id == alumno_id)
        .options(selectinload(BoletinHistorico.curso))
        .order_by(BoletinHistorico.ciclo_lectivo.desc())
    )
    result_bol = await db.execute(stmt_bol)
    boletines = result_bol.scalars().all()

    # Inscripción actual
    stmt_inscr = (
        select(InscripcionAlumno)
        .where(
            InscripcionAlumno.alumno_id == alumno_id,
            InscripcionAlumno.ciclo_lectivo == date.today().year,
        )
        .options(selectinload(InscripcionAlumno.curso))
    )
    result_inscr = await db.execute(stmt_inscr)
    inscripcion_actual = result_inscr.scalar_one_or_none()

    # Tutores/Familia
    stmt_tutores = (
        select(VinculoFamiliar)
        .where(VinculoFamiliar.alumno_id == alumno_id)
        .options(selectinload(VinculoFamiliar.tutor))
    )
    result_tutores = await db.execute(stmt_tutores)
    vinculos = result_tutores.scalars().all()

    return templates.TemplateResponse(
        "directivo/legajo.html",
        {
            "request": request,
            "directivo": directivo,
            "alumno": alumno,
            "documentos": documentos,
            "anotaciones": anotaciones,
            "sanciones": sanciones,
            "boletines": boletines,
            "inscripcion_actual": inscripcion_actual,
            "vinculos": vinculos,
            "categorias_anotacion": [c.value for c in CategoriaMedicaEnum],
            "tipos_sancion": [t.value for t in TipoSancionEnum],
            "success": success,
            "error": error,
        },
    )


@router.post("/legajos/{alumno_id}/documento")
async def legajo_actualizar_doc(
    alumno_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    doc_id: Optional[int] = Form(default=None),
    tipo_documento: str = Form(default=""),
    entregado: bool = Form(default=False),
    observaciones: str = Form(default=""),
):
    require_directivo(request)

    if doc_id:
        stmt = select(LegajoPermanenteDocumento).where(LegajoPermanenteDocumento.id == doc_id)
        result = await db.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc:
            doc.entregado = entregado
            doc.observaciones = observaciones.strip()
    else:
        if tipo_documento.strip():
            doc = LegajoPermanenteDocumento(
                alumno_id=alumno_id,
                tipo_documento=tipo_documento.strip(),
                entregado=entregado,
                observaciones=observaciones.strip(),
            )
            db.add(doc)

    await db.commit()
    return RedirectResponse(
        url=f"/directivo/legajos/{alumno_id}?success=Legajo+actualizado",
        status_code=303,
    )


@router.post("/legajos/{alumno_id}/anotacion")
async def legajo_nueva_anotacion(
    alumno_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    categoria: str = Form(...),
    descripcion: str = Form(...),
):
    directivo = require_directivo(request)

    anot = AnotacionEspecial(
        alumno_id=alumno_id,
        categoria=CategoriaMedicaEnum(categoria),
        descripcion=descripcion.strip(),
        fecha_registro=date.today(),
        autor_id=directivo.id,
    )
    db.add(anot)
    await db.commit()
    return RedirectResponse(
        url=f"/directivo/legajos/{alumno_id}?success=Anotación+registrada",
        status_code=303,
    )


@router.post("/legajos/{alumno_id}/sancion")
async def legajo_nueva_sancion(
    alumno_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tipo_sancion: str = Form(...),
    cantidad: int = Form(default=0),
    motivo: str = Form(...),
    fecha_sancion: str = Form(...),
):
    directivo = require_directivo(request)

    # Obtener inscripción actual
    stmt = select(InscripcionAlumno).where(
        InscripcionAlumno.alumno_id == alumno_id,
        InscripcionAlumno.ciclo_lectivo == date.today().year,
    )
    result = await db.execute(stmt)
    inscripcion = result.scalar_one_or_none()
    if not inscripcion:
        return RedirectResponse(
            url=f"/directivo/legajos/{alumno_id}?error=Alumno+sin+inscripción+activa",
            status_code=303,
        )

    try:
        fecha = datetime.strptime(fecha_sancion, "%Y-%m-%d").date()
    except ValueError:
        fecha = date.today()

    sancion = SancionDisciplinaria(
        inscripcion_id=inscripcion.id,
        tipo_sancion=TipoSancionEnum(tipo_sancion),
        cantidad_amonestaciones=cantidad,
        motivo=motivo.strip(),
        fecha_sancion=fecha,
        autor_id=directivo.id,
    )
    db.add(sancion)
    await db.commit()
    return RedirectResponse(
        url=f"/directivo/legajos/{alumno_id}?success=Sanción+registrada",
        status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CASOS DE BULLYING
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/casos", response_class=HTMLResponse)
async def casos_bullying(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    directivo = require_directivo(request)

    stmt = (
        select(CuadernoNotificacion)
        .where(
            CuadernoNotificacion.tipo_notificacion == TipoNotificacionEnum.INCIDENCIA_BULLYING,
            CuadernoNotificacion.receptor_id == directivo.id,
        )
        .options(selectinload(CuadernoNotificacion.emisor))
        .order_by(CuadernoNotificacion.fecha_envio.desc())
    )
    result = await db.execute(stmt)
    casos = result.scalars().all()

    return templates.TemplateResponse(
        "directivo/casos.html",
        {
            "request": request,
            "directivo": directivo,
            "casos": casos,
        },
    )


@router.post("/casos/{caso_id}/resolver")
async def resolver_caso(
    caso_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_directivo(request)
    stmt = select(CuadernoNotificacion).where(CuadernoNotificacion.id == caso_id)
    result = await db.execute(stmt)
    caso = result.scalar_one_or_none()
    if caso:
        caso.firmado = True
        from datetime import datetime
        caso.fecha_firma = datetime.utcnow()
        await db.commit()
    return RedirectResponse(url="/directivo/casos?success=Caso+marcado+como+resuelto", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# COMUNICADOS MASIVOS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/comunicados", response_class=HTMLResponse)
async def comunicados_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    directivo = require_directivo(request)

    stmt_cursos = select(Curso).where(Curso.anio == str(date.today().year))
    result = await db.execute(stmt_cursos)
    cursos = result.scalars().all()

    stmt_enviados = (
        select(CuadernoNotificacion)
        .where(
            CuadernoNotificacion.emisor_id == directivo.id,
            CuadernoNotificacion.tipo_notificacion == TipoNotificacionEnum.COMUNICADO,
        )
        .order_by(CuadernoNotificacion.fecha_envio.desc())
        .limit(20)
    )
    result_env = await db.execute(stmt_enviados)
    comunicados_enviados = result_env.scalars().all()

    return templates.TemplateResponse(
        "directivo/comunicados.html",
        {
            "request": request,
            "directivo": directivo,
            "cursos": cursos,
            "comunicados_enviados": comunicados_enviados,
            "success": success,
            "error": error,
        },
    )


@router.post("/comunicados/enviar")
async def comunicado_enviar(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    titulo: str = Form(...),
    contenido: str = Form(...),
    curso_id: Optional[int] = Form(default=None),
    requiere_firma: bool = Form(default=False),
):
    directivo = require_directivo(request)
    ciclo = date.today().year

    # Obtener destinatarios: tutores de los alumnos del curso o de toda la institución
    if curso_id:
        stmt = (
            select(VinculoFamiliar)
            .join(InscripcionAlumno, InscripcionAlumno.alumno_id == VinculoFamiliar.alumno_id)
            .where(
                InscripcionAlumno.curso_id == curso_id,
                InscripcionAlumno.ciclo_lectivo == ciclo,
            )
            .options(selectinload(VinculoFamiliar.tutor))
            .distinct()
        )
    else:
        stmt = (
            select(VinculoFamiliar)
            .join(InscripcionAlumno, InscripcionAlumno.alumno_id == VinculoFamiliar.alumno_id)
            .where(InscripcionAlumno.ciclo_lectivo == ciclo)
            .options(selectinload(VinculoFamiliar.tutor))
            .distinct()
        )

    result = await db.execute(stmt)
    vinculos = result.scalars().unique().all()

    enviados = 0
    tutores_notificados = set()
    for vinculo in vinculos:
        if vinculo.tutor_id in tutores_notificados:
            continue
        tutores_notificados.add(vinculo.tutor_id)

        notif = CuadernoNotificacion(
            emisor_id=directivo.id,
            receptor_id=vinculo.tutor_id,
            tipo_notificacion=TipoNotificacionEnum.COMUNICADO,
            titulo=titulo,
            contenido=contenido,
            requiere_firma=requiere_firma,
            curso_id=curso_id,
        )
        db.add(notif)
        enviados += 1

        background_tasks.add_task(
            despachar_notificacion,
            email_destinatario=vinculo.tutor.email,
            nombre_destinatario=vinculo.tutor.nombre,
            telefono=vinculo.tutor.telefono,
            titulo=titulo,
            contenido=contenido,
            tipo="COMUNICADO",
            requiere_firma=requiere_firma,
        )

    await db.commit()
    return RedirectResponse(
        url=f"/directivo/comunicados?success=Comunicado+enviado+a+{enviados}+familias",
        status_code=303,
    )