"""
EscudoEscolar — Punto de entrada FastAPI
SSR con Jinja2 · MySQL · No-JS First
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db, check_connection
from middleware.auth import AuthMiddleware
from routers import auth, alumno, tutor, docente, directivo, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        ok = await check_connection()
        if ok:
            print("✓ Conexión MySQL establecida")
        else:
            print("⚠ No se pudo verificar MySQL — revisá .env y docker-compose")
    except Exception as e:
        print(f"⚠ Base de datos: {e}")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Sistema integral de acompañamiento y bienestar escolar",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")
app.mount("/media", StaticFiles(directory=str(settings.MEDIA_DIR)), name="media")

app.include_router(auth.router)
app.include_router(alumno.router)
app.include_router(tutor.router)
app.include_router(docente.router)
app.include_router(directivo.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    try:
        db_ok = await check_connection()
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "app": settings.APP_NAME, "db": db_ok}
