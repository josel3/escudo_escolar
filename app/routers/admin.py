"""
EscudoEscolar — Router del Administrador
Gestión de usuarios, colegios, ticketera de incidencias, estadísticas globales
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from database import get_db
from security import hash_password
from models.models import (
    Usuario, Curso, Materia, AsignacionDocente, InscripcionAlumno,
    VinculoFamiliar, TicketeraIncidenciaAdmin, CalificacionRegular,
    ChatTutorIA, CuadernoNotificacion,
    RolEnum, NivelEnum, TurnoEnum, EstadoInscripcionEnum,
    PrioridadTicketEnum, EstadoTicketEnum,
)
from config import settings
from templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(request: Request) -> Usuario:
    user = getattr(request.state, "user", None)
    if not user or user.rol.value != "ADMIN":
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
    admin = require_admin(request)

    # Métricas globales
    conteos = {}
    for rol in RolEnum:
        stmt = select(func.count(Usuario.id)).where(Usuario.rol == rol, Usuario.activo == True)
        result = await db.execute(stmt)
        conteos[rol.value] = int(result.scalar() or 0)

    # Chats con Tutor IA (últimos 30 días)
    stmt_ia = select(func.count(ChatTutorIA.id))
    result_ia = await db.execute(stmt_ia)
    total_chats_ia = int(result_ia.scalar() or 0)

    # Tickets abiertos
    stmt_tickets = select(func.count(TicketeraIncidenciaAdmin.id)).where(
        TicketeraIncidenciaAdmin.estado == EstadoTicketEnum.ABIERTO
    )
    result_tickets = await db.execute(stmt_tickets)
    tickets_abiertos = int(result_tickets.scalar() or 0)

    # Notificaciones totales
    stmt_notif = select(func.count(CuadernoNotificacion.id))
    result_notif = await db.execute(stmt_notif)
    total_notif = int(result_notif.scalar() or 0)

    return templates.TemplateResponse(
            request,
        "admin/dashboard.html",
        {
            "admin": admin,
            "conteos": conteos,
            "total_chats_ia": total_chats_ia,
            "tickets_abiertos": tickets_abiertos,
            "total_notif": total_notif,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# GESTIÓN DE USUARIOS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
async def lista_usuarios(
    request: Request,
    db: AsyncSession = Depends(get_db),
    rol: Optional[str] = None,
    q: str = "",
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)

    stmt = select(Usuario).order_by(Usuario.rol, Usuario.nombre)
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    if q:
        stmt = stmt.where(Usuario.nombre.contains(q))

    result = await db.execute(stmt)
    usuarios = result.scalars().all()

    return templates.TemplateResponse(
             request,
        "admin/usuarios.html",
        {
            "admin": admin,
            "usuarios": usuarios,
            "roles": [r.value for r in RolEnum],
            "rol_filtro": rol,
            "q": q,
            "success": success,
            "error": error,
        },
    )


@router.get("/usuarios/nuevo", response_class=HTMLResponse)
async def nuevo_usuario_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    error: str = "",
):
    admin = require_admin(request)
    return templates.TemplateResponse(
             request,
        "admin/usuario_form.html",
        {
            "admin": admin,
            "roles": [r.value for r in RolEnum],
            "usuario": None,
            "error": error,
        },
    )


@router.post("/usuarios/nuevo")
async def nuevo_usuario_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    rol: str = Form(...),
    telefono: str = Form(default=""),
):
    require_admin(request)

    # Verificar email único
    stmt = select(Usuario).where(Usuario.email == email.lower().strip())
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        return RedirectResponse(
            url=f"/admin/usuarios/nuevo?error=El+email+{email}+ya+está+registrado",
            status_code=303,
        )

    usuario = Usuario(
        nombre=nombre.strip(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
        rol=RolEnum(rol),
        telefono=telefono.strip() or None,
    )
    db.add(usuario)
    await db.commit()
    return RedirectResponse(
        url=f"/admin/usuarios?success=Usuario+{nombre}+creado+correctamente",
        status_code=303,
    )


@router.post("/usuarios/{usuario_id}/toggle-activo")
async def toggle_usuario_activo(
    usuario_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    stmt = select(Usuario).where(Usuario.id == usuario_id)
    result = await db.execute(stmt)
    usuario = result.scalar_one_or_none()
    if usuario:
        usuario.activo = not usuario.activo
        await db.commit()
    return RedirectResponse(url="/admin/usuarios?success=Estado+actualizado", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# GESTIÓN ACADÉMICA: CURSOS, MATERIAS, ASIGNACIONES, INSCRIPCIONES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cursos", response_class=HTMLResponse)
async def cursos_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)
    stmt = select(Curso).order_by(Curso.anio.desc(), Curso.division)
    result = await db.execute(stmt)
    cursos = result.scalars().all()
    return templates.TemplateResponse(
            request,
        "admin/cursos.html",
        {
            "admin": admin,
            "cursos": cursos,
            "niveles": [n.value for n in NivelEnum],
            "turnos": [t.value for t in TurnoEnum],
            "success": success,
            "error": error,
        },
    )


@router.post("/cursos/nuevo")
async def nuevo_curso(
    request: Request,
    db: AsyncSession = Depends(get_db),
    anio: str = Form(...),
    nivel: str = Form(...),
    division: str = Form(...),
    turno: str = Form(...),
):
    require_admin(request)
    curso = Curso(
        anio=anio,
        nivel=NivelEnum(nivel),
        division=division.strip(),
        turno=TurnoEnum(turno),
    )
    db.add(curso)
    await db.commit()
    return RedirectResponse(url="/admin/cursos?success=Curso+creado", status_code=303)


@router.get("/materias", response_class=HTMLResponse)
async def materias_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)
    stmt = select(Materia).order_by(Materia.nombre)
    result = await db.execute(stmt)
    materias = result.scalars().all()
    return templates.TemplateResponse(
            request,
        "admin/materias.html",
        {
            "admin": admin,
            "materias": materias,
            "success": success,
            "error": error,
        },
    )


@router.post("/materias/nueva")
async def nueva_materia(
    request: Request,
    db: AsyncSession = Depends(get_db),
    nombre: str = Form(...),
    codigo: str = Form(...),
):
    require_admin(request)
    materia = Materia(nombre=nombre.strip(), codigo=codigo.strip().upper())
    db.add(materia)
    try:
        await db.commit()
        return RedirectResponse(url="/admin/materias?success=Materia+creada", status_code=303)
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url="/admin/materias?error=Código+de+materia+ya+existe",
            status_code=303,
        )


@router.get("/asignaciones", response_class=HTMLResponse)
async def asignaciones_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)

    stmt = (
        select(AsignacionDocente)
        .options(
            selectinload(AsignacionDocente.docente),
            selectinload(AsignacionDocente.materia),
            selectinload(AsignacionDocente.curso),
        )
        .order_by(AsignacionDocente.id)
    )
    result = await db.execute(stmt)
    asignaciones = result.scalars().all()

    stmt_docentes = select(Usuario).where(Usuario.rol == RolEnum.DOCENTE, Usuario.activo == True)
    result_d = await db.execute(stmt_docentes)
    docentes = result_d.scalars().all()

    stmt_materias = select(Materia).order_by(Materia.nombre)
    result_m = await db.execute(stmt_materias)
    materias = result_m.scalars().all()

    stmt_cursos = select(Curso).order_by(Curso.anio.desc(), Curso.division)
    result_c = await db.execute(stmt_cursos)
    cursos = result_c.scalars().all()

    return templates.TemplateResponse(
            request,
        "admin/asignaciones.html",
        {
            "admin": admin,
            "asignaciones": asignaciones,
            "docentes": docentes,
            "materias": materias,
            "cursos": cursos,
            "success": success,
            "error": error,
        },
    )


@router.post("/asignaciones/nueva")
async def nueva_asignacion(
    request: Request,
    db: AsyncSession = Depends(get_db),
    docente_id: int = Form(...),
    materia_id: int = Form(...),
    curso_id: int = Form(...),
):
    require_admin(request)
    asig = AsignacionDocente(
        docente_id=docente_id,
        materia_id=materia_id,
        curso_id=curso_id,
    )
    db.add(asig)
    try:
        await db.commit()
        return RedirectResponse(url="/admin/asignaciones?success=Asignación+creada", status_code=303)
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url="/admin/asignaciones?error=Esa+asignación+ya+existe",
            status_code=303,
        )


@router.get("/inscripciones", response_class=HTMLResponse)
async def inscripciones_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)

    stmt = (
        select(InscripcionAlumno)
        .options(
            selectinload(InscripcionAlumno.alumno),
            selectinload(InscripcionAlumno.curso),
        )
        .where(InscripcionAlumno.ciclo_lectivo == date.today().year)
        .order_by(InscripcionAlumno.id)
    )
    result = await db.execute(stmt)
    inscripciones = result.scalars().all()

    stmt_alumnos = select(Usuario).where(Usuario.rol == RolEnum.ALUMNO, Usuario.activo == True)
    result_a = await db.execute(stmt_alumnos)
    alumnos = result_a.scalars().all()

    stmt_tutores = select(Usuario).where(Usuario.rol == RolEnum.TUTOR, Usuario.activo == True)
    result_t = await db.execute(stmt_tutores)
    tutores = result_t.scalars().all()

    stmt_cursos = select(Curso).where(Curso.anio == str(date.today().year))
    result_c = await db.execute(stmt_cursos)
    cursos = result_c.scalars().all()

    return templates.TemplateResponse(
            request,
        "admin/inscripciones.html",
        {
            "admin": admin,
            "inscripciones": inscripciones,
            "alumnos": alumnos,
            "tutores": tutores,
            "cursos": cursos,
            "estados": [e.value for e in EstadoInscripcionEnum],
            "ciclo_actual": date.today().year,
            "success": success,
            "error": error,
        },
    )


@router.post("/inscripciones/nueva")
async def nueva_inscripcion(
    request: Request,
    db: AsyncSession = Depends(get_db),
    alumno_id: int = Form(...),
    curso_id: int = Form(...),
    ciclo_lectivo: int = Form(...),
    estado: str = Form(default="REGULAR"),
):
    require_admin(request)
    inscr = InscripcionAlumno(
        alumno_id=alumno_id,
        curso_id=curso_id,
        ciclo_lectivo=ciclo_lectivo,
        estado=EstadoInscripcionEnum(estado),
    )
    db.add(inscr)
    try:
        await db.commit()
        return RedirectResponse(url="/admin/inscripciones?success=Inscripción+creada", status_code=303)
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url="/admin/inscripciones?error=El+alumno+ya+está+inscripto+en+ese+curso+y+año",
            status_code=303,
        )


@router.post("/vinculos/nuevo")
async def nuevo_vinculo(
    request: Request,
    db: AsyncSession = Depends(get_db),
    alumno_id: int = Form(...),
    tutor_id: int = Form(...),
    parentesco: str = Form(...),
):
    require_admin(request)
    from models.models import VinculoFamiliar
    vinculo = VinculoFamiliar(
        alumno_id=alumno_id,
        tutor_id=tutor_id,
        parentesco=parentesco.strip(),
    )
    db.add(vinculo)
    try:
        await db.commit()
        return RedirectResponse(url="/admin/inscripciones?success=Vínculo+familiar+creado", status_code=303)
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url="/admin/inscripciones?error=Vínculo+ya+existe",
            status_code=303,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TICKETERA DE INCIDENCIAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/ticketera", response_class=HTMLResponse)
async def ticketera_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    estado: Optional[str] = None,
    prioridad: Optional[str] = None,
    success: str = "",
    error: str = "",
):
    admin = require_admin(request)

    stmt = (
        select(TicketeraIncidenciaAdmin)
        .options(selectinload(TicketeraIncidenciaAdmin.creador))
        .order_by(
            TicketeraIncidenciaAdmin.prioridad.desc(),
            TicketeraIncidenciaAdmin.fecha_creacion.desc(),
        )
    )
    if estado:
        stmt = stmt.where(TicketeraIncidenciaAdmin.estado == EstadoTicketEnum(estado))
    if prioridad:
        stmt = stmt.where(TicketeraIncidenciaAdmin.prioridad == PrioridadTicketEnum(prioridad))

    result = await db.execute(stmt)
    tickets = result.scalars().all()

    # Conteos por estado
    conteos_estado = {}
    for est in EstadoTicketEnum:
        stmt_c = select(func.count(TicketeraIncidenciaAdmin.id)).where(
            TicketeraIncidenciaAdmin.estado == est
        )
        result_c = await db.execute(stmt_c)
        conteos_estado[est.value] = int(result_c.scalar() or 0)

    return templates.TemplateResponse(
             request,
        "admin/ticketera.html",
        {
            "admin": admin,
            "tickets": tickets,
            "estados": [e.value for e in EstadoTicketEnum],
            "prioridades": [p.value for p in PrioridadTicketEnum],
            "estado_filtro": estado,
            "prioridad_filtro": prioridad,
            "conteos_estado": conteos_estado,
            "success": success,
            "error": error,
        },
    )


@router.post("/ticketera/{ticket_id}/estado")
async def actualizar_estado_ticket(
    ticket_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    nuevo_estado: str = Form(...),
    notas_resolucion: str = Form(default=""),
):
    require_admin(request)

    stmt = select(TicketeraIncidenciaAdmin).where(TicketeraIncidenciaAdmin.id == ticket_id)
    result = await db.execute(stmt)
    ticket = result.scalar_one_or_none()

    if ticket:
        ticket.estado = EstadoTicketEnum(nuevo_estado)
        if notas_resolucion:
            ticket.resolucion_notas = notas_resolucion
        if nuevo_estado in ("RESUELTO", "CERRADO"):
            ticket.fecha_resolucion = datetime.utcnow()
        await db.commit()

    return RedirectResponse(url="/admin/ticketera?success=Ticket+actualizado", status_code=303)


@router.get("/ticketera/nuevo", response_class=HTMLResponse)
async def nuevo_ticket_page(request: Request, error: str = ""):
    admin = require_admin(request)
    return templates.TemplateResponse(
            request,
        "admin/ticket_form.html",
        {
            "admin": admin,
            "prioridades": [p.value for p in PrioridadTicketEnum],
            "error": error,
        },
    )


@router.post("/ticketera/nuevo")
async def nuevo_ticket_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    modulo_afectado: str = Form(...),
    prioridad: str = Form(...),
    descripcion: str = Form(...),
):
    admin = require_admin(request)
    ticket = TicketeraIncidenciaAdmin(
        creador_id=admin.id,
        modulo_afectado=modulo_afectado.strip(),
        prioridad=PrioridadTicketEnum(prioridad),
        descripcion=descripcion.strip(),
    )
    db.add(ticket)
    await db.commit()
    return RedirectResponse(url="/admin/ticketera?success=Ticket+creado", status_code=303)