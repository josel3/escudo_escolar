"""
EscudoEscolar — Middleware de Autenticación por Cookies
Implementa el esquema No-JS First: sesiones en DB, sin JWT en localStorage
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import Usuario, Sesion


# ─────────────────────────────────────────────────────────────────────────────
# Rutas públicas (no requieren autenticación)
# ─────────────────────────────────────────────────────────────────────────────

PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/static",
    "/media",
    "/favicon.ico",
    "/health",
}


def es_ruta_publica(path: str) -> bool:
    for pub in PUBLIC_PATHS:
        if path == pub or path.startswith(pub + "/") or path.startswith("/static/"):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Middleware principal
# ─────────────────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Rutas públicas: pasar sin verificar
        if es_ruta_publica(path) or path == "/":
            return await call_next(request)

        session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)

        if not session_id:
            return RedirectResponse(
                url=f"/login?error=Sesión+no+iniciada",
                status_code=303
            )

        # Verificar sesión en base de datos
        async with AsyncSessionLocal() as db:
            usuario = await obtener_usuario_por_sesion(db, session_id)

        if not usuario:
            response = RedirectResponse(
                url="/login?error=Sesión+inválida+o+expirada",
                status_code=303
            )
            response.delete_cookie(settings.SESSION_COOKIE_NAME)
            return response

        if not usuario.activo:
            response = RedirectResponse(
                url="/login?error=Cuenta+desactivada",
                status_code=303
            )
            response.delete_cookie(settings.SESSION_COOKIE_NAME)
            return response

        # Verificar permisos de rol por prefijo de ruta
        rol = usuario.rol.value.lower()
        redireccion = verificar_permiso_ruta(path, rol)
        if redireccion:
            return RedirectResponse(url=redireccion, status_code=303)

        request.state.user = usuario
        request.state.session_id = session_id
        return await call_next(request)


def verificar_permiso_ruta(path: str, rol: str) -> Optional[str]:
    """
    Devuelve la URL de redirección si el rol no tiene acceso a la ruta.
    Retorna None si el acceso está permitido.
    """
    rutas_rol = {
        "alumno": "/alumno/",
        "tutor": "/tutor/",
        "docente": "/docente/",
        "directivo": "/directivo/",
        "admin": "/admin/",
    }

    # Directivos también pueden acceder a algunas rutas de docentes
    if rol == "directivo" and path.startswith("/docente/"):
        return None

    prefijo_rol = rutas_rol.get(rol)
    if prefijo_rol and path.startswith("/"):
        # Verificar que el path pertenece al rol correcto
        for r, prefijo in rutas_rol.items():
            if path.startswith(prefijo) and r != rol:
                # Admin puede ver todo
                if rol == "admin":
                    return None
                return f"/{rol}/dashboard?error=Acceso+no+autorizado"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Funciones de gestión de sesiones
# ─────────────────────────────────────────────────────────────────────────────

def generar_session_id() -> str:
    """Genera un ID de sesión criptográficamente seguro."""
    return secrets.token_urlsafe(64)


async def crear_sesion(
    db: AsyncSession,
    usuario_id: int,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Crea una nueva sesión en base de datos y devuelve el ID."""
    session_id = generar_session_id()
    expiracion = datetime.utcnow() + timedelta(seconds=settings.SESSION_MAX_AGE)

    sesion = Sesion(
        id=session_id,
        usuario_id=usuario_id,
        fecha_expiracion=expiracion,
        ip_address=ip,
        user_agent=user_agent[:255] if user_agent else None,
    )
    db.add(sesion)
    await db.commit()
    return session_id


async def obtener_usuario_por_sesion(
    db: AsyncSession, session_id: str
) -> Optional[Usuario]:
    """Busca y valida una sesión, devuelve el Usuario asociado o None."""
    stmt = (
        select(Sesion)
        .where(
            Sesion.id == session_id,
            Sesion.fecha_expiracion > datetime.utcnow(),
        )
    )
    result = await db.execute(stmt)
    sesion = result.scalar_one_or_none()

    if not sesion:
        return None

    stmt_user = select(Usuario).where(Usuario.id == sesion.usuario_id)
    result_user = await db.execute(stmt_user)
    return result_user.scalar_one_or_none()


async def eliminar_sesion(db: AsyncSession, session_id: str) -> None:
    """Elimina una sesión (logout)."""
    stmt = delete(Sesion).where(Sesion.id == session_id)
    await db.execute(stmt)
    await db.commit()


async def limpiar_sesiones_expiradas(db: AsyncSession) -> int:
    """Limpia sesiones expiradas. Llamar periódicamente."""
    stmt = delete(Sesion).where(Sesion.fecha_expiracion <= datetime.utcnow())
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


def set_session_cookie(response: Response, session_id: str) -> None:
    """Establece la cookie de sesión segura."""
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_id,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,  # Solo HTTPS en producción
    )


def delete_session_cookie(response: Response) -> None:
    """Elimina la cookie de sesión."""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )