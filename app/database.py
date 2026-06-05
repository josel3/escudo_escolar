"""
EscudoEscolar — Configuración y conexión a MySQL
"""

import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "escudo_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "escudo_pass")
DB_NAME = os.getenv("DB_NAME", "escudoescolar")

DATABASE_URL = (
    f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("DEBUG", "false").lower() == "true",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncSession:
    """Dependency para inyección de sesión de base de datos."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Crea todas las tablas si no existen (desarrollo)."""
    from app.models.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_connection():
    """Verifica conectividad con la base de datos."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        return result.fetchone() is not None