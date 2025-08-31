from typing import Any, Text, Dict, List, Optional
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import FollowupAction, EventType, SlotSet
from rasa_sdk.forms import FormValidationAction

# stdlib
import re
import difflib
import csv
import os
import io
from functools import lru_cache
import random
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONFIG · Rutas CSV (puedes sobrescribir con variables de entorno)
# ============================================================================
CSV_SINTOMAS_PATH = os.getenv("CSV_SINTOMAS_PATH", "data/sintomas.csv")
CSV_MEDICAMENTOS_PATH = os.getenv("CSV_MEDICAMENTOS_PATH", "data/medicamentos.csv")

# Carpeta para feedback
FEEDBACK_DIR = Path(os.getenv("FEEDBACK_DIR", "data/metrics"))
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_CSV = FEEDBACK_DIR / "feedback.csv"

# ============================================================================
# UTILIDADES GENERALES
# ============================================================================
def norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = (s
         .replace("á","a").replace("é","e").replace("í","i")
         .replace("ó","o").replace("ú","u").replace("ü","u").replace("ñ","n"))
    s = re.sub(r"\s+", " ", s)
    return s

EMERGENCIA_KEYWORDS = [
    "dolor de pecho", "dificultad para respirar", "falta de aire",
    "perdida de conciencia", "pérdida de conciencia"
]

def _open_csv_robusto(path: str):
    """
    Intenta abrir un CSV probando varias codificaciones: utf-8, utf-8-sig, cp1252, latin-1.
    Devuelve (file_obj, encoding_usada) o (None, None) si no existe.
    """
    if not os.path.exists(path):
        return None, None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            f = open(path, newline="", encoding=enc)
            _peek = f.read(2048)
            f.seek(0)
            return f, enc
        except Exception:
            continue
    try:
        raw = open(path, "rb").read()
        text = raw.decode("latin-1", errors="replace")
        return io.StringIO(text), "latin-1(replace)"
    except Exception:
        return None, None

# ============================================================================
# CSV · SÍNTOMAS
# ============================================================================
@lru_cache(maxsize=1)
def cargar_sintomas_desde_csv() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(CSV_SINTOMAS_PATH):
        return {}
    base: Dict[str, Dict[str, str]] = {}
    f, enc = _open_csv_robusto(CSV_SINTOMAS_PATH)
    if not f:
        return {}
    with f:
        reader = csv.DictReader(f)
        req = {
            "sintoma","medicamento","forma","dosis",
            "efectos_secundarios","advertencias","cuando_consultar","sinonimos"
        }
        if not req.issubset(set(reader.fieldnames or [])):
            return {}
        for row in reader:
            sintoma = (row.get("sintoma") or "").strip()
            if not sintoma:
                continue
            can = norm(sintoma)
            item = {
                "sintoma": sintoma,
                "medicamento": (row.get("medicamento") or "").strip(),
                "forma": (row.get("forma") or "").strip(),
                "dosis": (row.get("dosis") or "").strip(),
                "efectos_secundarios": (row.get("efectos_secundarios") or "").strip(),
                "advertencias": (row.get("advertencias") or "").strip(),
                "cuando_consultar": (row.get("cuando_consultar") or "").strip(),
            }
            base[can] = item
            sinonimos_raw = (row.get("sinonimos") or "").strip()
            if sinonimos_raw:
                for s in sinonimos_raw.split("|"):
                    s_norm = norm(s)
                    if s_norm and s_norm not in base:
                        base[s_norm] = item
    return base

def sintomas_canonicos() -> List[str]:
    db = cargar_sintomas_desde_csv()
    vistos, canon = set(), []
    for _, item in db.items():
        k = norm(item["sintoma"])
        if k not in vistos:
            canon.append(item["sintoma"])
            vistos.add(k)
    canon.sort()
    return canon

def similares_sintomas(texto: str, n: int = 5, cutoff: float = 0.70) -> List[str]:
    base = sintomas_canonicos()
    mapa = {norm(s): s for s in base}
    matches = difflib.get_close_matches(norm(texto), list(mapa.keys()), n=n, cutoff=cutoff)
    return [mapa[m] for m in matches if m in mapa]

def texto_lista_sintomas(max_cols: int = 3) -> str:
    nombres = [s.title() for s in sintomas_canonicos()]
    if not nombres:
        return "No hay síntomas configurados."
    col_len = (len(nombres) + max_cols - 1) // max_cols
    cols = [nombres[i*col_len:(i+1)*col_len] for i in range(max_cols)]
    width = max(len(s) for s in nombres)
    lines = []
    for i in range(col_len):
        row = []
        for c in cols:
            if i < len(c):
                row.append(c[i].ljust(width))
        lines.append("   ".join(row).rstrip())
    return "📋 *Síntomas disponibles*\n```\n" + "\n".join(lines) + "\n```\nEscribe el *síntoma* que presentas."

# ============================================================================
# CSV · MEDICAMENTOS
# ============================================================================
@lru_cache(maxsize=1)
def cargar_medicamentos_desde_csv() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(CSV_MEDICAMENTOS_PATH):
        return {}
    base: Dict[str, Dict[str, str]] = {}
    f, enc = _open_csv_robusto(CSV_MEDICAMENTOS_PATH)
    if not f:
        return {}
    with f:
        reader = csv.DictReader(f)
        req = {"nombre","descripcion","presentacion","uso","dosis",
               "efectos_secundarios","advertencias","consultar","sinonimos"}
        if not req.issubset(set(reader.fieldnames or [])):
            return {}
        for row in reader:
            nombre = (row.get("nombre") or "").strip()
            if not nombre:
                continue
            can = norm(nombre)
            item = {
                "nombre": nombre,
                "descripcion": (row.get("descripcion") or "").strip(),
                "presentacion": (row.get("presentacion") or "").strip(),
                "uso": (row.get("uso") or "").strip(),
                "dosis": (row.get("dosis") or "").strip(),
                "efectos_secundarios": (row.get("efectos_secundarios") or "").strip(),
                "advertencias": (row.get("advertencias") or "").strip(),
                "consultar": (row.get("consultar") or "").strip(),
            }
            base[can] = item
            sinonimos_raw = (row.get("sinonimos") or "").strip()
            if sinonimos_raw:
                for s in sinonimos_raw.split("|"):
                    s_norm = norm(s)
                    if s_norm and s_norm not in base:
                        base[s_norm] = item
    return base

def medicamentos_canonicos() -> List[str]:
    db = cargar_medicamentos_desde_csv()
    vistos, canon = set(), []
    for _, item in db.items():
        k = norm(item["nombre"])
        if k not in vistos:
            canon.append(item["nombre"])
            vistos.add(k)
    canon.sort()
    return canon

def similares_medicamentos(nombre: str, n: int = 5, cutoff: float = 0.70) -> List[str]:
    base = medicamentos_canonicos()
    mapa = {norm(s): s for s in base}
    matches = difflib.get_close_matches(norm(nombre), list(mapa.keys()), n=n, cutoff=cutoff)
    return [mapa[m] for m in matches if m in mapa]

def texto_lista_medicamentos(max_cols: int = 3) -> str:
    nombres = [s.title() for s in medicamentos_canonicos()]
    if not nombres:
        return "No hay medicamentos configurados."
    col_len = (len(nombres) + max_cols - 1) // max_cols
    cols = [nombres[i*col_len:(i+1)*col_len] for i in range(max_cols)]
    width = max(len(s) for s in nombres)
    lines = []
    for i in range(col_len):
        row = []
        for c in cols:
            if i < len(c):
                row.append(c[i].ljust(width))
        lines.append("   ".join(row).rstrip())
    return "📋 *Medicamentos disponibles*\n```\n" + "\n".join(lines) + "\n```\nEscribe el *nombre* que deseas consultar."

# ============================================================================
# ACCIONES · Opción 2: consultar medicamentos por nombre (vía CSV)
# ============================================================================
class ActionPedirMedicamentoNombre(Action):
    def name(self) -> Text:
        return "action_pedir_medicamento_nombre"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        dispatcher.utter_message(response="utter_pedir_medicamento_nombre")
        return []

class ActionListarMedicamentos(Action):
    def name(self) -> Text:
        return "action_listar_medicamentos"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        dispatcher.utter_message(text=texto_lista_medicamentos())
        dispatcher.utter_message(text="¿Qué medicamento deseas consultar?")
        return []

class ActionConsultarPorNombre(Action):
    def name(self) -> Text:
        return "action_consultar_por_nombre"

    def _es_comando_inicio(self, t: str) -> bool:
        return t in {
            "2", "consultar medicamentos por nombre", "consultar por nombre",
            "medicamento por nombre", "consulta de medicamento", "por nombre"
        }

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        texto = (tracker.latest_message.get("text") or "").strip()
        tnorm = norm(texto)

        # Inicio → pedir nombre
        if self._es_comando_inicio(tnorm):
            dispatcher.utter_message(response="utter_pedir_medicamento_nombre")
            return []

        # Atajos: listado
        if tnorm in {"medicamentos", "ver medicamentos", "listar medicamentos", "/listar_medicamentos"}:
            dispatcher.utter_message(text=texto_lista_medicamentos())
            dispatcher.utter_message(text="¿Qué medicamento deseas consultar?")
            return []

        # BD CSV
        db = cargar_medicamentos_desde_csv()
        if not db:
            dispatcher.utter_message(text="No se encontró el catálogo de medicamentos (CSV). Verifica el archivo.")
            return []

        # Coincidencia directa
        if tnorm in db:
            info = db[tnorm]
            ficha = (
                f"💊 *{info['nombre'].title()}*\n"
                f"• Descripción: {info['descripcion']}\n"
                f"• Presentación: {info['presentacion']}\n"
                f"• Uso recomendado: {info['uso']}\n"
                f"• Dosis (orientativa): {info['dosis']}\n"
                f"• Efectos secundarios: {info['efectos_secundarios']}\n"
                f"• Advertencias: {info['advertencias']}\n"
                f"• Consulta médica: {info['consultar']}\n\n"
                
            )
            
            dispatcher.utter_message(text=ficha)
            # === pedir calificación ===
            dispatcher.utter_message(
                text="¿Esta información te fue útil?",
                buttons=[
                    {"title": "⭐️⭐️⭐️⭐️⭐️ 5", "payload": '/enviar_calificacion{"rating":5}'},
                    {"title": "⭐️⭐️⭐️⭐️ 4",  "payload": '/enviar_calificacion{"rating":4}'},
                    {"title": "⭐️⭐️⭐️ 3",     "payload": '/enviar_calificacion{"rating":3}'},
                    {"title": "⭐️⭐️ 2",        "payload": '/enviar_calificacion{"rating":2}'},
                    {"title": "⭐️ 1",          "payload": '/enviar_calificacion{"rating":1}'},
                    {"title": "Omitir", "payload": "/volver_menu"}
                ]
            )
            dispatcher.utter_message(
                text="¿Deseas consultar *otro medicamento* o *volver al menú*?",
                buttons=[
                    {"title": "Otro medicamento", "payload": "/otro_medicamento"},
                    {"title": "Ver Medicamentos", "payload": "/listar_medicamentos"},
                    {"title": "Volver al menú", "payload": "/volver_menu"},
                ]
            )
            
            return [
                SlotSet("tipo_consulta", "medicamento"),
                SlotSet("entrada_usuario", tracker.latest_message.get("text")),
                SlotSet("item_resuelto", info["nombre"])
            ]

        # Sugerencias
        sugeridos = similares_medicamentos(tnorm, n=4, cutoff=0.70)
        if sugeridos:
            buttons = [{"title": s.title(), "payload": s} for s in sugeridos]
            buttons.append({"title": "Ver Medicamentos", "payload": "/listar_medicamentos"})
            buttons.append({"title": "Volver al menú", "payload": "/volver_menu"})
            dispatcher.utter_message(
                text=(f"No encontré “{texto}”. ¿Te refieres a alguno de estos? "
                      f"También puedes hacer clic en *Ver Medicamentos* para ver el catálogo completo."),
                buttons=buttons
            )
            return []

        # Sin parecidos
        dispatcher.utter_message(
            text="No encontré ese medicamento en mi catálogo. ¿Quieres ver el listado completo?",
            buttons=[
                {"title": "Ver Medicamentos", "payload": "/listar_medicamentos"},
                {"title": "Volver al menú", "payload": "/volver_menu"},
            ]
        )
        return []

# ============================================================================
# ACCIONES · Opción 1: consultar por SÍNTOMA (vía CSV)
# ============================================================================
class ActionConsultarMedicamento(Action):
    def name(self) -> Text:
        return "action_consultar_medicamento"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        user_text = (tracker.latest_message.get("text") or "").strip()
        tnorm = norm(user_text)

        # Emergencia
        if any(k in tnorm for k in EMERGENCIA_KEYWORDS):
            dispatcher.utter_message(
                text=("🚨 *Síntoma de posible emergencia detectado.* "
                      "Por tu seguridad, acude de inmediato al servicio de urgencias más cercano "
                      "o llama a los servicios médicos de emergencia.")
            )
            return []

        # Atajos listado
        if tnorm in {"ver","lista","listar","ver lista","ver sintomas","ver lista de sintomas","/listar_sintomas"}:
            dispatcher.utter_message(text=texto_lista_sintomas())
            dispatcher.utter_message(text="¿Qué síntoma presentas?")
            return []

        # Cargar base
        db = cargar_sintomas_desde_csv()
        if not db:
            dispatcher.utter_message(text="No se encontró el catálogo de síntomas (CSV). Verifica el archivo.")
            return []

        # Match directo
        if tnorm in db:
            info = db[tnorm]
            msg = (
                f"🩺 *Recomendación para {info['sintoma']}*\n"
                f"• Medicamento: {info.get('medicamento','-')}\n"
                f"• Forma: {info.get('forma','-')}\n"
                f"• Dosis adultos: {info.get('dosis','-')}\n"
                f"• Efectos secundarios: {info.get('efectos_secundarios','-')}\n"
                f"• Advertencias: {info.get('advertencias','-')}\n"
                f"• Consultar al médico: {info.get('cuando_consultar','-')}\n\n"
                
            )
            
            dispatcher.utter_message(text=msg)
            # === pedir calificación ===
            dispatcher.utter_message(
                text="¿Esta información te fue útil?",
                buttons=[
                    {"title": "⭐️⭐️⭐️⭐️⭐️ 5", "payload": '/enviar_calificacion{"rating":5}'},
                    {"title": "⭐️⭐️⭐️⭐️ 4",  "payload": '/enviar_calificacion{"rating":4}'},
                    {"title": "⭐️⭐️⭐️ 3",     "payload": '/enviar_calificacion{"rating":3}'},
                    {"title": "⭐️⭐️ 2",        "payload": '/enviar_calificacion{"rating":2}'},
                    {"title": "⭐️ 1",          "payload": '/enviar_calificacion{"rating":1}'},
                    {"title": "Omitir", "payload": "/volver_menu"}
                ]
            )
            dispatcher.utter_message(
                text="¿Quieres consultar *otro síntoma* o *volver al menú*?",
                buttons=[
                    {"title": "Otro síntoma", "payload": "/otro_sintoma"},
                    {"title": "Ver lista de síntomas", "payload": "/listar_sintomas"},
                    {"title": "Volver al menú", "payload": "/volver_menu"},
                ]
            )
            
            return [
                SlotSet("tipo_consulta", "sintoma"),
                SlotSet("entrada_usuario", tracker.latest_message.get("text")),
                SlotSet("item_resuelto", info["sintoma"])
            ]

        # Sugerencias
        sugeridos = similares_sintomas(tnorm, n=5, cutoff=0.70)
        if sugeridos:
            buttons = [{"title": s.title(), "payload": s} for s in sugeridos]
            buttons.append({"title": "Ver lista de síntomas", "payload": "/listar_sintomas"})
            buttons.append({"title": "Volver al menú", "payload": "/volver_menu"})
            dispatcher.utter_message(
                text=f"No reconocí “{user_text}”. ¿Te refieres a alguno de estos?",
                buttons=buttons
            )
            return []

        # Sin sugerencias
        dispatcher.utter_message(
            text="No reconozco ese síntoma. ¿Quieres ver el listado completo?",
            buttons=[
                {"title": "Ver lista de síntomas", "payload": "/listar_sintomas"},
                {"title": "Volver al menú", "payload": "/volver_menu"},
            ]
        )
        return []

class ActionListarSintomas(Action):
    def name(self) -> Text:
        return "action_listar_sintomas"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        dispatcher.utter_message(text=texto_lista_sintomas())
        dispatcher.utter_message(text="¿Qué síntoma presentas?")
        return []

# ============================================================================
# ACCIÓN · Menú
# ============================================================================
class ActionElegirOpcion(Action):
    def name(self) -> Text:
        return "action_elegir_opcion"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        opcion = norm(tracker.latest_message.get("text", ""))

        if opcion in {"1", "sintoma", "consultar por sintoma"}:
            dispatcher.utter_message(response="utter_solicitar_sintoma")
        elif opcion in {"2", "medicamento", "consultar por medicamento"}:
            dispatcher.utter_message(response="utter_pedir_medicamento_nombre")
        elif opcion in {"3", "ubicacion", "ubicacion de la farmacia", "donde", "donde estan"}:
            dispatcher.utter_message(response="utter_ubicacion")
        elif opcion in {"4", "horario", "horarios", "ver horarios", "horarios de atencion"}:
            dispatcher.utter_message(response="utter_horario")
        elif opcion in {"5", "farmaceutico", "hablar con un farmaceutico", "quiero hablar con alguien"}:
            dispatcher.utter_message(response="utter_derivar_farmaceutico")
            return [FollowupAction("contacto_ticket_form")]
        else:
            dispatcher.utter_message(text="Lo siento, no entendí tu opción. Por favor elige un número del 1 al 5.")
        return []

# ============================================================================
# OPCIÓN 5 · Form de contacto y envío por email
# ============================================================================
def _solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _valid_phone(s: str) -> bool:
    d = _solo_digitos(s)
    return 8 <= len(d) <= 12

def _valid_email(s: str) -> bool:
    if not s:
        return True
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s.strip()) is not None

def _norm_pref(s: str) -> Text:
    s = (s or "").lower()
    if "whats" in s or "wa" in s:
        return "WhatsApp"
    if "llam" in s or "tel" in s or "cel" in s:
        return "llamada"
    if "mail" in s or "correo" in s or "email" in s:
        return "email"
    return "llamada"

class ValidateContactoTicketForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_contacto_ticket_form"

    def validate_nombre(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> Dict[Text, Any]:
        v = (slot_value or "").strip()
        if len(v) >= 2:
            return {"nombre": v}
        dispatcher.utter_message(text="Necesito al menos un nombre válido. ¿Cuál es tu nombre completo?")
        return {"nombre": None}

    def validate_telefono(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> Dict[Text, Any]:
        if _valid_phone(slot_value):
            return {"telefono": _solo_digitos(slot_value)}
        dispatcher.utter_message(text="El número parece inválido. Escríbelo con solo dígitos (8 a 12).")
        return {"telefono": None}

    def validate_correo(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> Dict[Text, Any]:
        v = (slot_value or "").strip()
        if _valid_email(v):
            return {"correo": v}
        dispatcher.utter_message(text="Ese correo no parece válido. ¿Puedes verificarlo?")
        return {"correo": None}

    def validate_preferencia_contacto(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> Dict[Text, Any]:
        m = _norm_pref(slot_value)
        if m in {"llamada", "WhatsApp", "email"}:
            return {"preferencia_contacto": m}
        dispatcher.utter_message(text="¿Prefieres llamada, WhatsApp o email?")
        return {"preferencia_contacto": None}

    def validate_motivo(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> Dict[Text, Any]:
        v = (slot_value or "").strip()
        if len(v) >= 5:
            return {"motivo": v}
        dispatcher.utter_message(text="Cuéntame un poco más del motivo (5+ caracteres).")
        return {"motivo": None}

class ActionEnviarTicketEmail(Action):
    def name(self) -> Text:
        return "action_enviar_ticket_email"

    def _build_email(self, to_addr: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = "bot@tu-empresa.com"   # <-- ajusta
        msg["To"] = to_addr
        msg.set_content(body)
        return msg

    def _send_email(self, msg: EmailMessage) -> None:
        # Configura tu SMTP si deseas enviar correos reales
        # with smtplib.SMTP("localhost", 25) as s:
        #     s.send_message(msg)
        pass

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        nombre = tracker.get_slot("nombre")
        telefono = tracker.get_slot("telefono")
        correo = tracker.get_slot("correo")
        preferencia = tracker.get_slot("preferencia_contacto")
        motivo = tracker.get_slot("motivo")

        ticket_id = f"TKT-{random.randint(10000, 99999)}"
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

        company_inbox = "farmaceutico@tu-empresa.com"  # <-- AJUSTAR
        subject = f"[Chatbot] Nuevo ticket {ticket_id}"
        body = (
            f"Ticket: {ticket_id}\n"
            f"Fecha: {fecha}\n\n"
            f"Nombre: {nombre}\n"
            f"Teléfono: {telefono}\n"
            f"Correo: {correo or '(no proporcionado)'}\n"
            f"Preferencia de contacto: {preferencia}\n\n"
            f"Motivo:\n{motivo}\n"
        )

        msg = self._build_email(company_inbox, subject, body)
        try:
            self._send_email(msg)
        except Exception:
            dispatcher.utter_message(text="He registrado tu solicitud. Hubo un inconveniente enviando el correo, pero será atendida igualmente.")

        cola_correo = f" y copia a {correo}" if (correo and correo.strip()) else ""
        dispatcher.utter_message(
            response="utter_ticket_enviado",
            ticket_id=ticket_id,
            preferencia_contacto=preferencia,
            telefono=telefono,
            cola_correo=cola_correo,
        )

        return [
            SlotSet("nombre", None),
            SlotSet("telefono", None),
            SlotSet("correo", None),
            SlotSet("preferencia_contacto", None),
            SlotSet("motivo", None),
        ]

# ============================================================================
# ACCIONES · Recargar CSV en caliente
# ============================================================================
class ActionRecargarSintomas(Action):
    def name(self) -> Text:
        return "action_recargar_sintomas"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        try:
            cargar_sintomas_desde_csv.cache_clear()
            cargar_sintomas_desde_csv()
            dispatcher.utter_message(text="✅ Catálogo de *síntomas* recargado desde el CSV.")
        except Exception as e:
            dispatcher.utter_message(text=f"⚠️ No se pudo recargar síntomas: {e}")
        return []

class ActionRecargarMedicamentos(Action):
    def name(self) -> Text:
        return "action_recargar_medicamentos"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        try:
            cargar_medicamentos_desde_csv.cache_clear()
            cargar_medicamentos_desde_csv()
            dispatcher.utter_message(text="✅ Catálogo de *medicamentos* recargado desde el CSV.")
        except Exception as e:
            dispatcher.utter_message(text=f"⚠️ No se pudo recargar medicamentos: {e}")
        return []

class ActionRecargarTodo(Action):
    def name(self) -> Text:
        return "action_recargar_todo"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        msgs = []
        try:
            cargar_sintomas_desde_csv.cache_clear()
            cargar_sintomas_desde_csv()
            msgs.append("síntomas ✅")
        except Exception as e:
            msgs.append(f"síntomas ❌ ({e})")
        try:
            cargar_medicamentos_desde_csv.cache_clear()
            cargar_medicamentos_desde_csv()
            msgs.append("medicamentos ✅")
        except Exception as e:
            msgs.append(f"medicamentos ❌ ({e})")
        dispatcher.utter_message(text="🔄 Recarga completada: " + ", ".join(msgs))
        return []

# ============================================================================
# FEEDBACK · Calificación y comentario guardado en CSV
# ============================================================================
def _feedback_write_header_if_needed():
    if not FEEDBACK_CSV.exists() or FEEDBACK_CSV.stat().st_size == 0:
        with open(FEEDBACK_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "ts_iso", "rating", "comentario",
                "tipo_consulta", "entrada_usuario", "item_resuelto"
            ])

def guardar_feedback(rating: Optional[int], comentario: str, tipo: str, entrada: str, resuelto: str):
    _feedback_write_header_if_needed()
    with open(FEEDBACK_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            datetime.utcnow().isoformat(timespec="seconds"),
            rating if rating is not None else "",
            (comentario or "").strip(),
            (tipo or ""),
            (entrada or ""),
            (resuelto or "")
        ])

class ActionEnviarCalificacion(Action):
    def name(self) -> Text:
        return "action_enviar_calificacion"

    def run(self, dispatcher, tracker, domain):
        rating = tracker.get_slot("rating")

        # fallback por si no se llenó slot
        if not rating:
            ents = list(tracker.get_latest_entity_values("rating"))
            if ents:
                rating = ents[0]

        try:
            rating_int = int(rating) if rating else None
        except Exception:
            rating_int = None

        if rating_int is None or not (1 <= rating_int <= 5):
            dispatcher.utter_message(text="Por favor elige una calificación del 1 al 5.")
            return []

        tipo = tracker.get_slot("tipo_consulta")
        entrada = tracker.get_slot("entrada_usuario")
        resuelto = tracker.get_slot("item_resuelto")

        guardar_feedback(rating_int, "", tipo or "", entrada or "", resuelto or "")

        dispatcher.utter_message(text="¡Gracias por tu opinión! 🧡",
                 buttons=[
                    {"title": "Volver al menú", "payload": "/volver_menu"},
                ]
            )
        return [SlotSet("rating", None)]

class ActionPedirComentario(Action):
    def name(self) -> Text:
        return "action_pedir_comentario"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(text="¿Quieres agregar un comentario breve sobre la respuesta? Escríbelo ahora (o di *omitir*).")
        return []

class ActionReporteFeedback(Action):
    def name(self) -> Text:
        return "action_reporte_feedback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        if not FEEDBACK_CSV.exists():
            dispatcher.utter_message(text="⚠️ Aún no hay datos de feedback registrados.")
            return []

        total, suma, dist, con_coment = 0, 0, {i:0 for i in range(1,6)}, 0
        with open(FEEDBACK_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rating = row.get("rating")
                comentario = (row.get("comentario") or "").strip()
                try:
                    r = int(rating)
                    if 1 <= r <= 5:
                        total += 1
                        suma += r
                        dist[r] += 1
                        if comentario:
                            con_coment += 1
                except Exception:
                    continue

        if total == 0:
            dispatcher.utter_message(text="⚠️ No hay calificaciones registradas todavía.")
            return []

        promedio = suma / total
    

        # Armar distribución
        dist_text = "\n".join([f"⭐️ {i}: {dist[i]}" for i in range(5,0,-1)])

        reporte = (
            f"📊 *Reporte de Feedback*\n\n"
            f"Total de calificaciones: {total}\n"
            f"Promedio: {promedio:.2f} ⭐️\n\n"
            f"Distribución:\n{dist_text}\n\n"
        )

        dispatcher.utter_message(text=reporte)
        return []
