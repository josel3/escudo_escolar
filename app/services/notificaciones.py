"""
EscudoEscolar — Servicios de Notificación Multicanal
Email (SMTP) + WhatsApp Business API
Integrados con FastAPI BackgroundTasks para no bloquear respuestas
"""

import httpx
import logging
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

async def enviar_email(
    destinatario: str,
    nombre_destinatario: str,
    asunto: str,
    contenido_html: str,
    contenido_texto: Optional[str] = None,
) -> bool:
    """Envía un email usando SMTP. Retorna True si fue exitoso."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP no configurado, email no enviado.")
        return False

    try:
        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
        msg["To"] = f"{nombre_destinatario} <{destinatario}>"

        if contenido_texto:
            msg.attach(MIMEText(contenido_texto, "plain", "utf-8"))

        msg.attach(MIMEText(contenido_html, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=True,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
        )
        logger.info(f"Email enviado a {destinatario}: {asunto}")
        return True

    except Exception as e:
        logger.error(f"Error enviando email a {destinatario}: {e}")
        return False


def generar_html_notificacion(
    titulo: str,
    contenido: str,
    tipo: str,
    requiere_accion: bool = False,
    url_accion: str = "",
) -> str:
    """Genera el HTML responsivo para emails de notificación."""
    colores = {
        "INFORME": "#2563EB",
        "ALERTA_ACADEMICA": "#D97706",
        "INCIDENCIA_BULLYING": "#DC2626",
        "COMUNICADO": "#059669",
    }
    color = colores.get(tipo, "#4B5563")

    boton_html = ""
    if requiere_accion and url_accion:
        boton_html = f"""
        <div style="text-align:center;margin:24px 0;">
            <a href="{url_accion}"
               style="background:{color};color:#fff;padding:12px 28px;
                      border-radius:6px;text-decoration:none;font-weight:bold;
                      display:inline-block;">
                Ingresar al Sistema y Firmar
            </a>
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{titulo}</title>
    </head>
    <body style="font-family:'Segoe UI',sans-serif;background:#F3F4F6;margin:0;padding:0;">
        <div style="max-width:600px;margin:32px auto;background:#fff;
                    border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
            <div style="background:{color};padding:24px;color:#fff;">
                <h1 style="margin:0;font-size:20px;">🛡️ EscudoEscolar</h1>
                <p style="margin:4px 0 0;opacity:.85;font-size:13px;">{tipo.replace('_', ' ')}</p>
            </div>
            <div style="padding:28px;">
                <h2 style="color:#1F2937;margin-top:0;">{titulo}</h2>
                <div style="color:#374151;line-height:1.6;">
                    {contenido.replace(chr(10), '<br>')}
                </div>
                {boton_html}
            </div>
            <div style="background:#F9FAFB;padding:16px;text-align:center;
                        font-size:12px;color:#9CA3AF;border-top:1px solid #E5E7EB;">
                Este es un mensaje automático de EscudoEscolar. No responder a este email.
            </div>
        </div>
    </body>
    </html>
    """


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP
# ─────────────────────────────────────────────────────────────────────────────

async def enviar_whatsapp(
    telefono: str,
    mensaje: str,
    tipo_notificacion: str = "INFORME",
) -> bool:
    """
    Envía un mensaje por WhatsApp Business API.
    Solo se activa para incidencias BULLYING y alertas CRÍTICAS.
    """
    if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_ID:
        logger.warning("WhatsApp no configurado, mensaje no enviado.")
        return False

    # Normalizar número: formato E.164
    telefono_limpio = "".join(c for c in telefono if c.isdigit())
    if not telefono_limpio.startswith("54"):
        telefono_limpio = "54" + telefono_limpio

    url = f"{settings.WHATSAPP_API_URL}/{settings.WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_limpio,
        "type": "text",
        "text": {"body": f"🛡️ *EscudoEscolar*\n\n{mensaje}"},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"WhatsApp enviado a {telefono_limpio}")
            return True
    except Exception as e:
        logger.error(f"Error enviando WhatsApp a {telefono_limpio}: {e}")
        return False


def es_critica(tipo_notificacion: str) -> bool:
    """Determina si la notificación requiere envío por WhatsApp."""
    return tipo_notificacion in ("INCIDENCIA_BULLYING", "ALERTA_ACADEMICA")


# ─────────────────────────────────────────────────────────────────────────────
# TAREA DE FONDO: Disparar todas las notificaciones
# ─────────────────────────────────────────────────────────────────────────────

async def despachar_notificacion(
    email_destinatario: Optional[str],
    nombre_destinatario: str,
    telefono: Optional[str],
    titulo: str,
    contenido: str,
    tipo: str,
    requiere_firma: bool = False,
    url_firma: str = "",
):
    """
    Función principal de despacho multicanal.
    Diseñada para ejecutarse como BackgroundTask de FastAPI.
    """
    # 1. Email (siempre)
    if email_destinatario:
        html = generar_html_notificacion(
            titulo=titulo,
            contenido=contenido,
            tipo=tipo,
            requiere_accion=requiere_firma,
            url_accion=url_firma,
        )
        await enviar_email(
            destinatario=email_destinatario,
            nombre_destinatario=nombre_destinatario,
            asunto=f"[EscudoEscolar] {titulo}",
            contenido_html=html,
            contenido_texto=f"{titulo}\n\n{contenido}",
        )

    # 2. WhatsApp (solo para alertas críticas)
    if telefono and es_critica(tipo):
        mensaje_wa = f"*{titulo}*\n\n{contenido}"
        if requiere_firma and url_firma:
            mensaje_wa += f"\n\n🔗 Ingresar al sistema: {url_firma}"
        await enviar_whatsapp(telefono, mensaje_wa, tipo)