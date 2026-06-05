# EscudoEscolar

Sistema integral de acompañamiento y bienestar escolar (EdTech argentina).  
**Stack:** FastAPI · Jinja2 SSR · MySQL · enfoque **No-JS First**.

## Módulos

| Rol | Funciones principales |
|-----|----------------------|
| **Alumno** | Dashboard semáforo, cuaderno, Tutor IA (texto/audio), tareas, reporte de bullying |
| **Tutor / Familia** | Seguimiento de hijos, firmas del cuaderno, solicitud de reuniones |
| **Docente** | Carga de notas (manual/CSV), asistencia, tareas, comunicaciones |
| **Directivo** | Estadísticas, legajo digital, casos bullying, comunicados masivos |
| **Admin** | Usuarios, cursos, materias, asignaciones, inscripciones, ticketera |

## Requisitos

- Python 3.10+
- MySQL 8.0 (o Docker)

## Instalación rápida

```bash
# 1. Base de datos
docker compose up -d

# 2. Entorno Python
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r app/requirements.txt

# 3. Variables de entorno
copy .env.example .env

# 4. Datos de demo
python scripts/seed.py

# 5. Servidor
python run.py
```

Abrí [http://localhost:8000](http://localhost:8000)

## Usuarios de demostración

Contraseña para todos: `escudo123`

| Email | Rol |
|-------|-----|
| admin@escudoescolar.ar | Admin |
| directivo@escudoescolar.ar | Directivo |
| docente@escudoescolar.ar | Docente |
| tutor@escudoescolar.ar | Tutor |
| alumno@escudoescolar.ar | Alumno |

## Estructura

```
app/
  main.py              # FastAPI + middleware + estáticos
  database.py          # MySQL async (SQLAlchemy)
  models/models.py     # Esquema V1 + V2
  routers/             # Rutas por rol
  services/            # Tutor IA (Gemini), notificaciones
  templates/           # Jinja2 SSR
  static/css/          # Estilos nativos
scripts/seed.py        # Datos de prueba
definitions/           # PDFs de diseño
```

## Documentación de diseño

- `definitions/documento_diseno_escudo_escolar.pdf` (V1)
- `definitions/documento_diseno_escudo_escolar_v2.pdf` (V2)

## Variables opcionales

- `GEMINI_API_KEY` — Tutor IA conversacional
- `SMTP_*` — Emails del cuaderno
- `WHATSAPP_*` — Alertas críticas (bullying / alertas académicas)

---

*EscudoEscolar — Los Sin Chamba · 2025*
