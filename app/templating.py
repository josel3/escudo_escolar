"""Instancia única de Jinja2 para toda la aplicación."""

from fastapi.templating import Jinja2Templates

from app.config import settings

templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


def _fmt_fecha(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        if hasattr(value, "hour"):
            return value.strftime("%d/%m/%Y %H:%M")
        return value.strftime("%d/%m/%Y")
    return str(value)


templates.env.filters["fmt_fecha"] = _fmt_fecha
templates.env.globals["app_name"] = settings.APP_NAME
