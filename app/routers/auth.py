"""
EscudoEscolar — Autenticación (login / logout / redirección por rol)
"""

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.security import verify_password
from app.templating import templates
from app.database import get_db, AsyncSessionLocal
from app.models.models import Usuario
from app.middleware.auth import (
    crear_sesion,
    eliminar_sesion,
    obtener_usuario_por_sesion,
    set_session_cookie,
    delete_session_cookie,
)

router = APIRouter(tags=["auth"])

DASHBOARD_POR_ROL = {
    "ADMIN": "/admin/dashboard",
    "DIRECTIVO": "/directivo/dashboard",
    "DOCENTE": "/docente/dashboard",
    "TUTOR": "/tutor/dashboard",
    "ALUMNO": "/alumno/dashboard",
}


def dashboard_url(rol: str) -> str:
    return DASHBOARD_POR_ROL.get(rol, "/login")


@router.get("/", response_class=HTMLResponse)
async def inicio(request: Request):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        async with AsyncSessionLocal() as db:
            usuario = await obtener_usuario_por_sesion(db, session_id)
        if usuario and usuario.activo:
            return RedirectResponse(
                url=dashboard_url(usuario.rol.value),
                status_code=303,
            )
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", success: str = ""):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        async with AsyncSessionLocal() as db:
            usuario = await obtener_usuario_por_sesion(db, session_id)
        if usuario and usuario.activo:
            return RedirectResponse(
                url=dashboard_url(usuario.rol.value),
                status_code=303,
            )

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error,
            "success": success,
            "app_name": settings.APP_NAME,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    email_norm = email.lower().strip()

    stmt = select(Usuario).where(Usuario.email == email_norm)
    result = await db.execute(stmt)
    usuario = result.scalar_one_or_none()

    if not usuario or not verify_password(password, usuario.password_hash):
        return RedirectResponse(
            url="/login?error=Credenciales+incorrectas",
            status_code=303,
        )

    if not usuario.activo:
        return RedirectResponse(
            url="/login?error=Cuenta+desactivada.+Contactá+a+la+institución",
            status_code=303,
        )

    session_id = await crear_sesion(
        db,
        usuario.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(
        url=dashboard_url(usuario.rol.value),
        status_code=303,
    )
    set_session_cookie(response, session_id)
    return response


@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        await eliminar_sesion(db, session_id)

    response = RedirectResponse(url="/login?success=Sesión+cerrada+correctamente", status_code=303)
    delete_session_cookie(response)
    return response
