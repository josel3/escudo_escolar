"""
EscudoEscolar — Configuración central de la aplicación
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

class Settings:
    # App
    APP_NAME = "EscudoEscolar"
    APP_VERSION = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Seguridad
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-CAMBIAR-EN-PRODUCCION")
    SESSION_MAX_AGE: int = int(os.getenv("SESSION_MAX_AGE", "86400"))
    SESSION_COOKIE_NAME: str = "escudo_session"

    # Semáforo académico
    NOTA_VERDE: float = 7.0
    NOTA_AMARILLA: float = 4.0

    # Rutas
    MEDIA_DIR: Path = BASE_DIR / os.getenv("MEDIA_DIR", "media")
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    STATIC_DIR: Path = BASE_DIR / "static"

    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Email
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "EscudoEscolar")

    # WhatsApp
    WHATSAPP_API_URL: str = os.getenv("WHATSAPP_API_URL", "")
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "")

    def semaforo_color(self, nota: float) -> str:
        if nota >= self.NOTA_VERDE:
            return "verde"
        elif nota >= self.NOTA_AMARILLA:
            return "amarillo"
        return "rojo"

    def semaforo_css(self, nota: float) -> str:
        color = self.semaforo_color(nota)
        return {
            "verde": "semaforo-verde",
            "amarillo": "semaforo-amarillo",
            "rojo": "semaforo-rojo",
        }[color]


settings = Settings()

# Asegurar que existan los directorios necesarios
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
(settings.MEDIA_DIR / "audio").mkdir(exist_ok=True)
(settings.MEDIA_DIR / "csv").mkdir(exist_ok=True)