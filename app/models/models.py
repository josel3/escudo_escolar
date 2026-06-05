"""
EscudoEscolar — Modelos de Base de Datos (SQLAlchemy ORM)
Esquema relacional completo según documentos de diseño V1.0 + V2.0
"""

from datetime import datetime, date
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date,
    DECIMAL, TIMESTAMP, ForeignKey, Enum, SmallInteger, UniqueConstraint,
    func
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class RolEnum(str, PyEnum):
    ADMIN = "ADMIN"
    DIRECTIVO = "DIRECTIVO"
    DOCENTE = "DOCENTE"
    TUTOR = "TUTOR"
    ALUMNO = "ALUMNO"

class NivelEnum(str, PyEnum):
    PRIMARIO = "PRIMARIO"
    SECUNDARIO = "SECUNDARIO"
    TERCIARIO = "TERCIARIO"

class TurnoEnum(str, PyEnum):
    MANANA = "MANANA"
    TARDE = "TARDE"
    VESPERTINO = "VESPERTINO"

class EstadoInscripcionEnum(str, PyEnum):
    REGULAR = "REGULAR"
    RECURSANTE = "RECURSANTE"
    PROMOVIDO = "PROMOVIDO"
    LIBRE = "LIBRE"

class EstadoFinalEnum(str, PyEnum):
    APROBADO = "APROBADO"
    REPITE = "REPITE"
    CON_MATERIAS_PREVIAS = "CON_MATERIAS_PREVIAS"

class AsistenciaEstadoEnum(str, PyEnum):
    PRESENTE = "PRESENTE"
    AUSENTE_JUSTIFICADO = "AUSENTE_JUSTIFICADO"
    AUSENTE_INJUSTIFICADO = "AUSENTE_INJUSTIFICADO"
    MEDIA_FALTA = "MEDIA_FALTA"

class TipoNotificacionEnum(str, PyEnum):
    INFORME = "INFORME"
    ALERTA_ACADEMICA = "ALERTA_ACADEMICA"
    INCIDENCIA_BULLYING = "INCIDENCIA_BULLYING"
    COMUNICADO = "COMUNICADO"
    ALERTA_TUTOR_IA = "ALERTA_TUTOR_IA"

class RolMensajeEnum(str, PyEnum):
    USER = "USER"
    MODEL = "MODEL"

class CategoriaMedicaEnum(str, PyEnum):
    MEDICA = "MEDICA"
    PSICOPEDAGOGICA = "PSICOPEDAGOGICA"
    ADAPTACION_CURRICULAR = "ADAPTACION_CURRICULAR"
    OTRO = "OTRO"

class TipoSancionEnum(str, PyEnum):
    APERCIBIMIENTO = "APERCIBIMIENTO"
    AMONESTACION = "AMONESTACION"
    SUSPENSION = "SUSPENSION"

class PrioridadTicketEnum(str, PyEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"

class EstadoTicketEnum(str, PyEnum):
    ABIERTO = "ABIERTO"
    EN_PROCESO = "EN_PROCESO"
    RESUELTO = "RESUELTO"
    CERRADO = "CERRADO"


# ─────────────────────────────────────────────────────────────────────────────
# TABLAS BASE (V1.0)
# ─────────────────────────────────────────────────────────────────────────────

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    rol = Column(Enum(RolEnum), nullable=False)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(30), nullable=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(TIMESTAMP, server_default=func.now())

    # Relaciones
    tutorizado_por = relationship("VinculoFamiliar", foreign_keys="VinculoFamiliar.alumno_id", back_populates="alumno")
    tutores = relationship("VinculoFamiliar", foreign_keys="VinculoFamiliar.tutor_id", back_populates="tutor")
    inscripciones = relationship("InscripcionAlumno", foreign_keys="InscripcionAlumno.alumno_id", back_populates="alumno")
    asignaciones_docente = relationship("AsignacionDocente", foreign_keys="AsignacionDocente.docente_id", back_populates="docente")
    notificaciones_enviadas = relationship("CuadernoNotificacion", foreign_keys="CuadernoNotificacion.emisor_id", back_populates="emisor")
    notificaciones_recibidas = relationship("CuadernoNotificacion", foreign_keys="CuadernoNotificacion.receptor_id", back_populates="receptor")
    chat_ia = relationship(
        "ChatTutorIA", foreign_keys="ChatTutorIA.alumno_id", back_populates="alumno"
    )
    legajo_documentos = relationship(
        "LegajoPermanenteDocumento",
        foreign_keys="LegajoPermanenteDocumento.alumno_id",
        back_populates="alumno",
    )
    anotaciones = relationship(
        "AnotacionEspecial",
        foreign_keys="AnotacionEspecial.alumno_id",
        back_populates="alumno",
    )
    anotaciones_registradas = relationship(
        "AnotacionEspecial",
        foreign_keys="AnotacionEspecial.autor_id",
        back_populates="autor",
    )
    boletines = relationship(
        "BoletinHistorico",
        foreign_keys="BoletinHistorico.alumno_id",
        back_populates="alumno",
    )
    tickets_creados = relationship(
        "TicketeraIncidenciaAdmin",
        foreign_keys="TicketeraIncidenciaAdmin.creador_id",
        back_populates="creador",
    )

    def __repr__(self):
        return f"<Usuario {self.nombre} [{self.rol}]>"


class VinculoFamiliar(Base):
    __tablename__ = "vinculos_familiares"

    alumno_id = Column(Integer, ForeignKey("usuarios.id"), primary_key=True)
    tutor_id = Column(Integer, ForeignKey("usuarios.id"), primary_key=True)
    parentesco = Column(String(50), nullable=False)

    alumno = relationship("Usuario", foreign_keys=[alumno_id], back_populates="tutorizado_por")
    tutor = relationship("Usuario", foreign_keys=[tutor_id], back_populates="tutores")


class CuadernoNotificacion(Base):
    __tablename__ = "cuaderno_notificaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emisor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    receptor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    tipo_notificacion = Column(Enum(TipoNotificacionEnum), nullable=False)
    titulo = Column(String(150), nullable=False)
    contenido = Column(Text, nullable=False)
    fecha_envio = Column(TIMESTAMP, server_default=func.now())
    requiere_firma = Column(Boolean, default=False)
    firmado = Column(Boolean, default=False)
    fecha_firma = Column(TIMESTAMP, nullable=True)
    # Para comunicados masivos (NULL = todos según scope)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=True)

    emisor = relationship("Usuario", foreign_keys=[emisor_id], back_populates="notificaciones_enviadas")
    receptor = relationship("Usuario", foreign_keys=[receptor_id], back_populates="notificaciones_recibidas")
    curso = relationship("Curso", back_populates="notificaciones")


class ChatTutorIA(Base):
    __tablename__ = "chat_tutor_ia"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    rol_mensaje = Column(Enum(RolMensajeEnum), nullable=False)
    texto_contenido = Column(Text, nullable=False)
    audio_url = Column(String(255), nullable=True)
    fecha_registro = Column(TIMESTAMP, server_default=func.now())

    alumno = relationship(
        "Usuario", foreign_keys=[alumno_id], back_populates="chat_ia"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABLAS ACADÉMICAS (V2.0)
# ─────────────────────────────────────────────────────────────────────────────

class Curso(Base):
    __tablename__ = "cursos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anio = Column(String(10), nullable=False)
    nivel = Column(Enum(NivelEnum), nullable=False)
    division = Column(String(50), nullable=False)
    turno = Column(Enum(TurnoEnum), nullable=False)

    inscripciones = relationship("InscripcionAlumno", back_populates="curso")
    asignaciones = relationship("AsignacionDocente", back_populates="curso")
    boletines = relationship("BoletinHistorico", back_populates="curso")
    notificaciones = relationship("CuadernoNotificacion", back_populates="curso")

    @property
    def nombre_completo(self):
        return f"{self.division} ({self.turno.value.capitalize()}) — {self.anio}"


class Materia(Base):
    __tablename__ = "materias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    codigo = Column(String(20), unique=True, nullable=False)

    asignaciones = relationship("AsignacionDocente", back_populates="materia")


class AsignacionDocente(Base):
    __tablename__ = "asignaciones_docentes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    docente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    materia_id = Column(Integer, ForeignKey("materias.id"), nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("docente_id", "materia_id", "curso_id", name="uq_asignacion"),
    )

    docente = relationship("Usuario", back_populates="asignaciones_docente")
    materia = relationship("Materia", back_populates="asignaciones")
    curso = relationship("Curso", back_populates="asignaciones")
    calificaciones = relationship("CalificacionRegular", back_populates="asignacion_docente")
    tareas = relationship("Tarea", back_populates="asignacion_docente")


class InscripcionAlumno(Base):
    __tablename__ = "inscripciones_alumnos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=False)
    ciclo_lectivo = Column(Integer, nullable=False)
    estado = Column(Enum(EstadoInscripcionEnum), default=EstadoInscripcionEnum.REGULAR)

    __table_args__ = (
        UniqueConstraint("alumno_id", "curso_id", "ciclo_lectivo", name="uq_inscripcion"),
    )

    alumno = relationship("Usuario", back_populates="inscripciones")
    curso = relationship("Curso", back_populates="inscripciones")
    calificaciones = relationship("CalificacionRegular", back_populates="inscripcion")
    asistencias = relationship("Asistencia", back_populates="inscripcion")
    sanciones = relationship("SancionDisciplinaria", back_populates="inscripcion")


class CalificacionRegular(Base):
    __tablename__ = "calificaciones_regulares"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inscripcion_id = Column(Integer, ForeignKey("inscripciones_alumnos.id"), nullable=False)
    asignacion_docente_id = Column(Integer, ForeignKey("asignaciones_docentes.id"), nullable=False)
    trimestre = Column(SmallInteger, nullable=False)  # 1, 2 o 3
    nota = Column(DECIMAL(4, 2), nullable=False)
    fecha_carga = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("inscripcion_id", "asignacion_docente_id", "trimestre", name="uq_calificacion"),
    )

    inscripcion = relationship("InscripcionAlumno", back_populates="calificaciones")
    asignacion_docente = relationship("AsignacionDocente", back_populates="calificaciones")


class BoletinHistorico(Base):
    __tablename__ = "boletines_historicos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id"), nullable=False)
    ciclo_lectivo = Column(Integer, nullable=False)
    promedio_general = Column(DECIMAL(4, 2), nullable=True)
    estado_final = Column(Enum(EstadoFinalEnum), nullable=True)
    fecha_cierre = Column(TIMESTAMP, server_default=func.now())

    alumno = relationship(
        "Usuario", foreign_keys=[alumno_id], back_populates="boletines"
    )
    curso = relationship("Curso", back_populates="boletines")


class Asistencia(Base):
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inscripcion_id = Column(Integer, ForeignKey("inscripciones_alumnos.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    estado = Column(Enum(AsistenciaEstadoEnum), nullable=False)
    valor_falta = Column(DECIMAL(3, 2), default=0.00)

    __table_args__ = (
        UniqueConstraint("inscripcion_id", "fecha", name="uq_asistencia_dia"),
    )

    inscripcion = relationship("InscripcionAlumno", back_populates="asistencias")


class LegajoPermanenteDocumento(Base):
    __tablename__ = "legajo_permanente_documentos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo_documento = Column(String(100), nullable=False)
    entregado = Column(Boolean, default=False)
    observaciones = Column(Text, nullable=True)
    fecha_actualizacion = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    alumno = relationship(
        "Usuario", foreign_keys=[alumno_id], back_populates="legajo_documentos"
    )


class AnotacionEspecial(Base):
    __tablename__ = "anotaciones_especiales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    categoria = Column(Enum(CategoriaMedicaEnum), nullable=False)
    descripcion = Column(Text, nullable=False)
    fecha_registro = Column(Date, nullable=False, default=date.today)
    autor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    alumno = relationship(
        "Usuario", foreign_keys=[alumno_id], back_populates="anotaciones"
    )
    autor = relationship(
        "Usuario", foreign_keys=[autor_id], back_populates="anotaciones_registradas"
    )


class SancionDisciplinaria(Base):
    __tablename__ = "sanciones_disciplinarias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inscripcion_id = Column(Integer, ForeignKey("inscripciones_alumnos.id"), nullable=False)
    tipo_sancion = Column(Enum(TipoSancionEnum), nullable=False)
    cantidad_amonestaciones = Column(Integer, default=0)
    motivo = Column(Text, nullable=False)
    fecha_sancion = Column(Date, nullable=False, default=date.today)
    autor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    inscripcion = relationship("InscripcionAlumno", back_populates="sanciones")
    autor = relationship("Usuario", foreign_keys=[autor_id])


class Tarea(Base):
    __tablename__ = "tareas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asignacion_docente_id = Column(Integer, ForeignKey("asignaciones_docentes.id"), nullable=False)
    titulo = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=False)
    fecha_entrega = Column(Date, nullable=False)
    fecha_creacion = Column(TIMESTAMP, server_default=func.now())

    asignacion_docente = relationship("AsignacionDocente", back_populates="tareas")


class TicketeraIncidenciaAdmin(Base):
    __tablename__ = "ticketera_incidencias_admin"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    modulo_afectado = Column(String(100), nullable=False)
    prioridad = Column(Enum(PrioridadTicketEnum), nullable=False, default=PrioridadTicketEnum.MEDIA)
    estado = Column(Enum(EstadoTicketEnum), nullable=False, default=EstadoTicketEnum.ABIERTO)
    descripcion = Column(Text, nullable=False)
    fecha_creacion = Column(TIMESTAMP, server_default=func.now())
    fecha_resolucion = Column(TIMESTAMP, nullable=True)
    resolucion_notas = Column(Text, nullable=True)

    creador = relationship(
        "Usuario", foreign_keys=[creador_id], back_populates="tickets_creados"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SESIONES
# ─────────────────────────────────────────────────────────────────────────────

class Sesion(Base):
    __tablename__ = "sesiones"

    id = Column(String(128), primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(TIMESTAMP, server_default=func.now())
    fecha_expiracion = Column(TIMESTAMP, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)