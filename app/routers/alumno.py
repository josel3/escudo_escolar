"""
EscudoEscolar — Router del Alumno
Dashboard, cuaderno, tutor IA, reporte de bullying, tareas
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Usuario, InscripcionAlumno, CalificacionRegular, CuadernoNotificacion,
    ChatTutorIA, Tarea, AsignacionDocente, Materia, Curso, Asistencia,
    TipoNotificacionEnum, RolMensajeEnum, VinculoFamiliar,
)
from app.config import settings
from app.templating import templates
from app.services import tutor_ia as ia_service
from app.services.notificaciones import despachar_notificacion

router = APIRouter(prefix="/alumno", tags=["alumno"])


def require_alumno(request: Request) -> Usuario:
    user = getattr(request.state, "user", None)
    if not user or user.rol.value != "ALUMNO":
        raise Exception("No autorizado")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    alumno = require_alumno(request)
    ciclo_actual = date.today().year

    # Inscripción activa
    stmt = (
        select(InscripcionAlumno)
        .where(
            InscripcionAlumno.alumno_id == alumno.id,
            InscripcionAlumno.ciclo_lectivo == ciclo_actual,
        )
        .options(selectinload(InscripcionAlumno.curso))
    )
    result = await db.execute(stmt)
    inscripcion = result.scalar_one_or_none()

    materias_con_notas = []
    total_faltas = 0.0
    porcentaje_asistencia = 100.0

    if inscripcion:
        # Notas del trimestre actual
        trimestre_actual = ((date.today().month - 1) // 4) + 1
        stmt_notas = (
            select(CalificacionRegular)
            .where(CalificacionRegular.inscripcion_id == inscripcion.id)
            .options(
                selectinload(CalificacionRegular.asignacion_docente)
                .selectinload(AsignacionDocente.materia)
            )
        )
        result_notas = await db.execute(stmt_notas)
        calificaciones = result_notas.scalars().all()

        # Agrupar por materia
        por_materia: dict = {}
        for cal in calificaciones:
            m = cal.asignacion_docente.materia
            if m.id not in por_materia:
                por_materia[m.id] = {"nombre": m.nombre, "notas": []}
            por_materia[m.id]["notas"].append({"trimestre": cal.trimestre, "nota": float(cal.nota)})

        for mid, datos in por_materia.items():
            notas_vals = [n["nota"] for n in datos["notas"]]
            promedio = sum(notas_vals) / len(notas_vals) if notas_vals else 0
            materias_con_notas.append({
                "nombre": datos["nombre"],
                "promedio": round(promedio, 2),
                "notas": datos["notas"],
                "css_semaforo": settings.semaforo_css(promedio),
            })

        # Asistencia
        stmt_asist = select(
            func.sum(Asistencia.valor_falta)
        ).where(Asistencia.inscripcion_id == inscripcion.id)
        result_asist = await db.execute(stmt_asist)
        total_faltas = float(result_asist.scalar() or 0)

        stmt_dias = select(func.count(Asistencia.id)).where(
            Asistencia.inscripcion_id == inscripcion.id
        )
        result_dias = await db.execute(stmt_dias)
        total_dias = int(result_dias.scalar() or 1)
        porcentaje_asistencia = round(
            ((total_dias - total_faltas) / total_dias * 100) if total_dias > 0 else 100, 1
        )

    # Notificaciones sin leer
    stmt_notif = (
        select(func.count(CuadernoNotificacion.id))
        .where(
            CuadernoNotificacion.receptor_id == alumno.id,
            CuadernoNotificacion.firmado == False,
        )
    )
    result_notif = await db.execute(stmt_notif)
    notificaciones_pendientes = int(result_notif.scalar() or 0)

    return templates.TemplateResponse(
        "alumno/dashboard.html",
        {
            "request": request,
            "alumno": alumno,
            "inscripcion": inscripcion,
            "materias": sorted(materias_con_notas, key=lambda x: x["nombre"]),
            "total_faltas": total_faltas,
            "porcentaje_asistencia": porcentaje_asistencia,
            "notificaciones_pendientes": notificaciones_pendientes,
            "ciclo_actual": ciclo_actual,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# CUADERNO DE NOTIFICACIONES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cuaderno", response_class=HTMLResponse)
async def cuaderno(request: Request, db: AsyncSession = Depends(get_db)):
    alumno = require_alumno(request)

    stmt = (
        select(CuadernoNotificacion)
        .where(CuadernoNotificacion.receptor_id == alumno.id)
        .options(selectinload(CuadernoNotificacion.emisor))
        .order_by(CuadernoNotificacion.fecha_envio.desc())
    )
    result = await db.execute(stmt)
    notificaciones = result.scalars().all()

    return templates.TemplateResponse(
        "alumno/cuaderno.html",
        {
            "request": request,
            "alumno": alumno,
            "notificaciones": notificaciones,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# TUTOR IA
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tutor-ia", response_class=HTMLResponse)
async def tutor_ia_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    error: str = "",
):
    alumno = require_alumno(request)

    # Historial de chat (últimos 30 mensajes)
    stmt = (
        select(ChatTutorIA)
        .where(ChatTutorIA.alumno_id == alumno.id)
        .order_by(ChatTutorIA.fecha_registro.asc())
        .limit(30)
    )
    result = await db.execute(stmt)
    historial = result.scalars().all()

    return templates.TemplateResponse(
        "alumno/tutor_ia.html",
        {
            "request": request,
            "alumno": alumno,
            "historial": historial,
            "error": error,
        },
    )


@router.post("/tutor-ia")
async def tutor_ia_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    mensaje: str = Form(default=""),
    audio: Optional[UploadFile] = File(default=None),
    solo_texto: bool = Form(default=False),
):
    alumno = require_alumno(request)

    # 1. Obtener texto de la consulta
    texto_consulta = mensaje.strip()

    if audio and audio.filename:
        audio_bytes = await audio.read()
        if audio_bytes:
            transcripcion = await ia_service.transcribir_audio(
                audio_bytes, mime_type=audio.content_type or "audio/ogg"
            )
            if transcripcion:
                texto_consulta = transcripcion

    if not texto_consulta and not audio:
        return RedirectResponse(
            url="/alumno/tutor-ia?error=Escribí+un+mensaje+o+grabá+un+audio",
            status_code=303,
        )

    # 2. Guardar mensaje del alumno
    msg_alumno = ChatTutorIA(
        alumno_id=alumno.id,
        rol_mensaje=RolMensajeEnum.USER,
        texto_contenido=texto_consulta,
    )
    db.add(msg_alumno)
    await db.flush()

    # 3. Cargar historial para contexto
    stmt = (
        select(ChatTutorIA)
        .where(ChatTutorIA.alumno_id == alumno.id)
        .order_by(ChatTutorIA.fecha_registro.asc())
        .limit(20)
    )
    result = await db.execute(stmt)
    historial_db = result.scalars().all()
    historial = [
        {"rol": h.rol_mensaje.value, "texto": h.texto_contenido}
        for h in historial_db
    ]

    # 4. Obtener inscripción para saber el nivel
    ciclo = date.today().year
    stmt_inscr = (
        select(InscripcionAlumno)
        .where(
            InscripcionAlumno.alumno_id == alumno.id,
            InscripcionAlumno.ciclo_lectivo == ciclo,
        )
        .options(selectinload(InscripcionAlumno.curso))
    )
    result_inscr = await db.execute(stmt_inscr)
    inscripcion = result_inscr.scalar_one_or_none()
    nivel = inscripcion.curso.nivel.value if inscripcion else "SECUNDARIO"

    # 5. Procesar con Gemini
    respuesta = await ia_service.procesar_consulta_tutor(
        texto_consulta=texto_consulta,
        historial=historial,
        nivel_alumno=nivel,
        nombre_alumno=alumno.nombre.split()[0],
    )

    json_text = ia_service.extract_json_object(respuesta)
    print("Respuesta cruda de Gemini:", respuesta)
    print("JSON extraído:", json_text)
    if json_text:
        try:
            respuesta_json = json.loads(json_text)
        except json.JSONDecodeError:
            respuesta_json = {}
    else:
        respuesta_json = {}

    alerta_detectada = respuesta_json.get("alerta_detectada", False)
    alerta_motivo = respuesta_json.get("alerta_motivo", "")
    respuesta_texto = respuesta_json.get("respuesta_alumno", respuesta)

    # 6. Generar audio si corresponde
    audio_url = None
    if not solo_texto:
        audio_url = await ia_service.generar_audio_respuesta(respuesta_texto, alumno.id)
        ia_service.limpiar_audios_viejos(alumno.id)

    # 7. Guardar respuesta del modelo
    msg_model = ChatTutorIA(
        alumno_id=alumno.id,
        rol_mensaje=RolMensajeEnum.MODEL,
        texto_contenido=respuesta_texto,
        audio_url=audio_url,
    )
    db.add(msg_model)
    await db.commit()

    # 8. Si se detectó una alerta, crear notificación para directivos, padres y docentes
    if alerta_detectada:
        titulo = "Alerta de Riesgo Detectada por Tutor IA"
        contenido = (
            f"El Tutor IA detectó una posible situación de riesgo con el siguiente motivo:\n\n"
            f"{alerta_motivo}\n\n"
            f"Consulta del alumno: {texto_consulta}\n"
            f"Respuesta del tutor IA: {respuesta_texto}"
        )

        destinatarios: dict[int, Usuario] = {}

        stmt_dirs = select(Usuario).where(Usuario.rol == "DIRECTIVO", Usuario.activo == True)
        result_dirs = await db.execute(stmt_dirs)
        for directivo in result_dirs.scalars().all():
            destinatarios[directivo.id] = directivo

        stmt_tutores = (
            select(Usuario)
            .join(VinculoFamiliar, VinculoFamiliar.tutor_id == Usuario.id)
            .where(VinculoFamiliar.alumno_id == alumno.id)
        )
        result_tutores = await db.execute(stmt_tutores)
        for tutor in result_tutores.scalars().all():
            destinatarios[tutor.id] = tutor

        if inscripcion:
            stmt_docentes = (
                select(Usuario)
                .join(AsignacionDocente, AsignacionDocente.docente_id == Usuario.id)
                .where(AsignacionDocente.curso_id == inscripcion.curso_id)
                .distinct()
            )
            result_docentes = await db.execute(stmt_docentes)
            for docente_destino in result_docentes.scalars().all():
                destinatarios[docente_destino.id] = docente_destino

        for receptor in destinatarios.values():
            notif = CuadernoNotificacion(
                emisor_id=alumno.id,
                receptor_id=receptor.id,
                tipo_notificacion=TipoNotificacionEnum.ALERTA_TUTOR_IA,
                titulo=titulo,
                contenido=contenido,
                requiere_firma=False,
            )
            db.add(notif)

        await db.commit()

    return RedirectResponse(url="/alumno/tutor-ia", status_code=303)


@router.post("/tutor-ia/limpiar")
async def limpiar_chat(request: Request, db: AsyncSession = Depends(get_db)):
    alumno = require_alumno(request)
    from sqlalchemy import delete
    stmt = delete(ChatTutorIA).where(ChatTutorIA.alumno_id == alumno.id)
    await db.execute(stmt)
    await db.commit()
    return RedirectResponse(url="/alumno/tutor-ia", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# REPORTE DE BULLYING
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reportar-bullying", response_class=HTMLResponse)
async def reporte_bullying_page(
    request: Request, error: str = "", success: str = ""
):
    alumno = require_alumno(request)
    return templates.TemplateResponse(
        "alumno/reportar_bullying.html",
        {
            "request": request,
            "alumno": alumno,
            "error": error,
            "success": success,
        },
    )


@router.post("/reportar-bullying")
async def reporte_bullying_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    descripcion: str = Form(...),
    anonimo: bool = Form(default=True),
):
    alumno = require_alumno(request)

    titulo = "Reporte de Incidencia de Bullying"
    contenido = descripcion
    if not anonimo:
        contenido = f"Reportado por: {alumno.nombre}\n\n{descripcion}"

    # Crear notificación para todos los directivos
    stmt_dirs = select(Usuario).where(Usuario.rol == "DIRECTIVO", Usuario.activo == True)
    result_dirs = await db.execute(stmt_dirs)
    directivos = result_dirs.scalars().all()

    for directivo in directivos:
        notif = CuadernoNotificacion(
            emisor_id=alumno.id,
            receptor_id=directivo.id,
            tipo_notificacion=TipoNotificacionEnum.INCIDENCIA_BULLYING,
            titulo=titulo,
            contenido=contenido,
            requiere_firma=False,
        )
        db.add(notif)

        # Despachar email y WhatsApp en background
        background_tasks.add_task(
            despachar_notificacion,
            email_destinatario=directivo.email,
            nombre_destinatario=directivo.nombre,
            telefono=directivo.telefono,
            titulo=titulo,
            contenido=contenido,
            tipo="INCIDENCIA_BULLYING",
        )

    await db.commit()
    return RedirectResponse(
        url="/alumno/reportar-bullying?success=Tu+reporte+fue+enviado+al+equipo+directivo",
        status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TAREAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tareas", response_class=HTMLResponse)
async def tareas(request: Request, db: AsyncSession = Depends(get_db)):
    alumno = require_alumno(request)
    ciclo = date.today().year

    stmt = (
        select(InscripcionAlumno)
        .where(
            InscripcionAlumno.alumno_id == alumno.id,
            InscripcionAlumno.ciclo_lectivo == ciclo,
        )
    )
    result = await db.execute(stmt)
    inscripcion = result.scalar_one_or_none()

    tareas_list = []
    if inscripcion:
        stmt_tareas = (
            select(Tarea)
            .join(AsignacionDocente)
            .where(AsignacionDocente.curso_id == inscripcion.curso_id)
            .options(
                selectinload(Tarea.asignacion_docente)
                .selectinload(AsignacionDocente.materia)
            )
            .order_by(Tarea.fecha_entrega.asc())
        )
        result_tareas = await db.execute(stmt_tareas)
        tareas_list = result_tareas.scalars().all()

    hoy = date.today()
    return templates.TemplateResponse(
        "alumno/tareas.html",
        {
            "request": request,
            "alumno": alumno,
            "tareas": tareas_list,
            "hoy": hoy,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# MIS NOTAS (historial completo)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mis-notas", response_class=HTMLResponse)
async def mis_notas(request: Request, db: AsyncSession = Depends(get_db)):
    alumno = require_alumno(request)

    stmt = (
        select(InscripcionAlumno)
        .where(InscripcionAlumno.alumno_id == alumno.id)
        .options(
            selectinload(InscripcionAlumno.curso),
            selectinload(InscripcionAlumno.calificaciones)
            .selectinload(CalificacionRegular.asignacion_docente)
            .selectinload(AsignacionDocente.materia),
        )
        .order_by(InscripcionAlumno.ciclo_lectivo.desc())
    )
    result = await db.execute(stmt)
    inscripciones = result.scalars().all()

    return templates.TemplateResponse(
        "alumno/mis_notas.html",
        {
            "request": request,
            "alumno": alumno,
            "inscripciones": inscripciones,
            "semaforo_css": settings.semaforo_css,
        },
    )