"""
EscudoEscolar — Servicio del Tutor IA (Gemini)
Maneja texto, audio (STT) y generación de voz (TTS) vía Google Gemini
"""

import os
import re
import uuid
import base64
import logging
from typing import Optional
from pathlib import Path
from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

NIVEL_INSTRUCCIONES = {
    "PRIMARIO": (
        "Sos un tutor escolar amigable para alumnos de primaria (6 a 12 años). "
        "Usá un lenguaje muy simple, con ejemplos cotidianos y muchos emojis. "
        "Sé paciente, alentador y nunca uses términos técnicos sin explicarlos. "
        "Si el alumno parece triste o preocupado, mostrá empatía antes de responder la pregunta."
    ),
    "SECUNDARIO": (
        "Sos un tutor escolar para alumnos de secundaria (13 a 17 años). "
        "Usá un lenguaje claro y directo, con ejemplos relevantes para adolescentes. "
        "Podés usar algo de jerga juvenil argentina, pero con moderación. "
        "Si el alumno expresa frustración o ansiedad académica, validá sus sentimientos "
        "y ofrecé estrategias de estudio concretas."
    ),
    "TERCIARIO": (
        "Sos un tutor académico para estudiantes de nivel terciario o universitario. "
        "Usá un lenguaje técnico apropiado pero accesible. "
        "Fomentá el pensamiento crítico y la investigación autónoma. "
        "Si el alumno tiene dificultades, orientalo con preguntas socráticas antes de dar la respuesta directa."
    ),
}


async def get_gemini_client():
    """Inicializa el cliente de Gemini.

    Preferimos el SDK oficial `google-genai` (`from google import genai`).
    Si no está instalado, se intenta usar el SDK anterior `google-generativeai`.
    """
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.debug("Usando paquete google-genai para Gemini")
        return client
    except ImportError:
        logger.error("No se encontró ningún SDK Gemini instalado (google-genai o google-generativeai).")
        return None
    except Exception as e:
        logger.error(f"Error configurando Gemini: {e}")
        return None


async def procesar_consulta_tutor(
    texto_consulta: str,
    historial: list[dict],
    nivel_alumno: str = "SECUNDARIO",
    nombre_alumno: str = "alumno",
) -> str:
    """
    Procesa una consulta de texto con Gemini y devuelve la respuesta.
    
    Args:
        texto_consulta: La pregunta o mensaje del alumno
        historial: Lista de mensajes previos [{role, parts}]
        nivel_alumno: PRIMARIO, SECUNDARIO o TERCIARIO
        nombre_alumno: Nombre para personalizar la respuesta
    """
    if not settings.GEMINI_API_KEY:
        return (
            "Lo siento, el Tutor IA no está disponible en este momento. Por favor consultá con tu docente."
        )

    try:
        client = await get_gemini_client()
        if client is None:
            raise RuntimeError("SDK Gemini no disponible")

        system_instruction = (
            NIVEL_INSTRUCCIONES.get(nivel_alumno, NIVEL_INSTRUCCIONES["SECUNDARIO"])
            + f"""\nEl nombre del alumno es {nombre_alumno}. Tratalo de 'vos' (lunfardo argentino).
            Responde a sus dudas de forma clara, adaptada estrictamente a su nivel cognitivo basándote en el audio que te envían.
            Además, actúas como un filtro de seguridad. Debes analizar el contenido para detectar situaciones de riesgo grave (bullying, violencia, autolesiones, abuso o entornos del hogar peligrosos).
            DEBES responder ÚNICAMENTE con un objeto JSON válido con la siguiente estructura, sin textos adicionales ni bloques de código markdown fuera del JSON:
       
         {{
          "respuesta_alumno": "Tu explicación pedagógica aquí orientada al alumno de {nivel_alumno}.",
          "alerta_detectada": true o false (boolean),
          "alerta_motivo": "Explicación detallada del riesgo detectado, o null si de alerta_detectada es false"
         }}
        """
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.4,

        )

        # Construir historial compatible con Gemini clásico
        history_gemini = []
        for msg in historial[-20:]:  # Últimos 20 mensajes para contexto
            role = "user" if msg["rol"] == "USER" else "model"
            history_gemini.append({
                "role": role,
                "parts": [msg["texto"]],
            })

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                texto_consulta               
            ],
            config=config
        )
        return response.text or '{"respuesta_alumno": "Lo siento, no pude generar una respuesta en este momento.", "alerta_detectada": false, "alerta_motivo": null}'

    except Exception as e:
        logger.error(f"Error consultando Gemini: {e}")
        return (
            "Tuve un problema al procesar tu consulta. "
            "Intentá de nuevo en un momento, o escribile a tu docente."
        )


def extract_json_object(raw_text: str) -> str | None:
    """Extrae el primer objeto JSON válido que aparece entre llaves en un texto.

    Esto elimina cualquier texto fuera del primer bloque JSON completo.
    """
    if not raw_text:
        return None

    start = raw_text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for idx, char in enumerate(raw_text[start:], start=start):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw_text[start:idx + 1]

    return None


async def transcribir_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """
    Transcribe audio a texto usando las capacidades multimodales de Gemini.
    """
    if not settings.GEMINI_API_KEY:
        return ""

    try:
        client = await get_gemini_client()
        if client is None:
            return ""


        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

        audio_input = types.AudioInput(
            data=audio_base64,
            mime_type=mime_type,
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                audio_input, 
                "Escucha atentamente el audio del alumno, analiza su duda y genera la respuesta estructurada en el JSON requerido."
            ],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Eres un asistente de transcripción de audio. Tu tarea es transcribir exactamente lo que dice el audio en español. Solo devuélve el texto transcripto, sin comentarios ni explicaciones."
                )
            )
        )
        return response.text or ""
    
    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        return ""

def sanitize_text_for_tts(og_text: str) -> str:
    """
    Limpia un texto eliminando marcas de formato Markdown y caracteres especiales
    para que motores de Text-to-Speech (TTS) lo lean de forma fluida y natural.
    """
    if not og_text:
        return ""
        
    # Creamos una tabla de traducción que mapea todas las comillas posibles a "nada" (None)
    delimiters = str.maketrans('', '', '"\'“”‘’')

    # Limpiamos el texto de forma segura y ultra rápida
    delimiters_fixed = og_text.translate(delimiters)

    # 1. Eliminar asteriscos de negrita/itálica (**texto** o *texto*)
    clean_text = re.sub(r'\*+', '', delimiters_fixed)
    
    # 2. Eliminar guiones de listas o viñetas al inicio de las líneas
    clean_text = re.sub(r'(?:^|\n)\s*-\s*', ' ', clean_text)
    
    # 3. Eliminar otros caracteres de formato MD comunes (#, _, `, ~)
    clean_text = re.sub(r'[#_~]', '', clean_text)
    
    # 4. Limpiar espacios dobles o saltos de línea excesivos sobrantes
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return clean_text

async def generar_audio_respuesta(texto: str, alumno_id: int) -> Optional[str]:
    """
    Genera un archivo de audio de la respuesta del tutor.
    Usa gTTS como fallback cuando Gemini TTS no está disponible.
    Devuelve la URL relativa del archivo o None si falla.
    """
    try:
        from gtts import gTTS
        import asyncio

        filename = f"tutor_{alumno_id}_{uuid.uuid4().hex[:8]}.mp3"
        filepath = settings.MEDIA_DIR / "audio" / filename

        #limpiar el texto para TTS
        texto_sanitizado = sanitize_text_for_tts(texto)

        # Ejecutar gTTS en un thread para no bloquear el event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: gTTS(text=texto_sanitizado, lang="es", slow=False).save(str(filepath)),
        )

        return f"/media/audio/{filename}"

    except ImportError:
        logger.warning("gTTS no instalado, audio no generado.")
        return None
    except Exception as e:
        logger.error(f"Error generando audio TTS: {e}")
        return None


def limpiar_audios_viejos(alumno_id: int, max_archivos: int = 10):
    """Limpia archivos de audio viejos de un alumno para ahorrar espacio."""
    audio_dir = settings.MEDIA_DIR / "audio"
    archivos = sorted(
        audio_dir.glob(f"tutor_{alumno_id}_*.mp3"),
        key=lambda p: p.stat().st_mtime,
    )
    for archivo in archivos[:-max_archivos]:
        try:
            archivo.unlink()
        except Exception:
            pass