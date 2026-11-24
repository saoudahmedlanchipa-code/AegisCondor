#!/usr/bin/env python3
"""
Aegis Condor - Sistema de seguridad en alturas (Raspberry Pi 4)

Un solo programa que:
  1. Lee el sensor PIR y la cámara (es el ÚNICO que abre la cámara)
  2. Vigila una VALLA VIRTUAL dibujada sobre la imagen (zona de riesgo)
  3. Emite la alerta: sirena, aviso rojo en pantalla, foto y registro
  4. Comparte todo con la app del celular mediante un servidor web (puerto 5000)

Hilos:
  - Hilo principal : cámara + PIR + valla virtual + alarma + ventana
  - Hilo servidor  : Flask (reutiliza la última imagen, no vuelve a abrir la cámara)

Teclas (con la ventana del video seleccionada):
  h  mostrar / ocultar ayuda       a  armar / desarmar
  z  dibujar la valla virtual      s  silenciar la sirena
  m  cambiar modo de detección     f  foto manual
  q / ESC  salir

Uso:
  python3 aegis_condor.py             # en la Raspberry
  python3 aegis_condor.py --simular   # en un PC, sin sensor ni cámara (para probar la app)
"""
import argparse
import json
import logging
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

# ---------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------
PIN_PIR = 4              # GPIO 4 = Pin físico 7
PIN_BUZZER = None        # Ej: 17 para un buzzer activo en GPIO 17 (Pin 11). None = sin buzzer
ANCHO, ALTO = 640, 480
COOLDOWN_FOTOS = 3       # segundos mínimos entre fotos
DURACION_ALERTA = 5      # segundos que sigue la alerta después del último movimiento
PUERTO = 5000
# Si la imagen sale con colores cambiados (personas azules), deja esto en True.
# Si con True los colores se ven mal, cámbialo a False.
INVERTIR_COLORES = True

# Valla virtual
UMBRAL_VALLA = 0.02      # fracción de la zona que debe tener movimiento (0.02 = 2 %). Más alto = menos sensible
AREA_MINIMA = 400        # área mínima (px) de un objeto en movimiento para considerarlo
MODOS = {
    "pir_y_valla": "PIR + VALLA",   # alerta si el PIR detecta Y hay movimiento dentro de la valla (recomendado)
    "valla": "SOLO VALLA",          # alerta solo con la cámara (movimiento dentro de la valla)
    "pir": "SOLO PIR",              # alerta solo con el PIR (como la versión anterior)
}

if getattr(sys, "frozen", False):
    DIR_BASE = os.path.dirname(sys.executable)
else:
    DIR_BASE = os.path.dirname(os.path.abspath(__file__))

CARPETA_CAPTURAS = os.path.join(DIR_BASE, "capturas_pir")
ARCHIVO_REGISTRO = os.path.join(DIR_BASE, "registro_alertas.txt")
ARCHIVO_SONIDO = os.path.join(DIR_BASE, ".alarma.wav")
ARCHIVO_VALLA = os.path.join(DIR_BASE, "valla_virtual.json")
os.makedirs(CARPETA_CAPTURAS, exist_ok=True)

HAY_PANTALLA = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
VENTANA = "Aegis Condor - Monitor de Seguridad"


# ---------------------------------------------------------------
# Módulo de alerta: sirena + buzzer opcional
# ---------------------------------------------------------------
class Alarma:
    def __init__(self, simular=False):
        self.proceso = None
        self.reproductor = shutil.which("aplay") or shutil.which("paplay")
        self.buzzer = None
        crear_sonido_alarma()
        if PIN_BUZZER is not None and not simular:
            from gpiozero import Buzzer
            self.buzzer = Buzzer(PIN_BUZZER)
            print(f"🔔 Buzzer activo en GPIO {PIN_BUZZER}")
        if self.reproductor:
            print(f"🔊 Alarma sonora lista ({os.path.basename(self.reproductor)})")
        else:
            print("⚠️  No se encontró 'aplay': la alarma usará el pitido de la terminal")

    def sonar(self):
        if self.buzzer is not None and not self.buzzer.is_active:
            self.buzzer.beep(on_time=0.25, off_time=0.25, n=4)
        if self.reproductor:
            if self.proceso is None or self.proceso.poll() is not None:
                self.proceso = subprocess.Popen([self.reproductor, ARCHIVO_SONIDO],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL)
        else:
            print("\a", end="", flush=True)

    def detener(self):
        if self.proceso is not None and self.proceso.poll() is None:
            self.proceso.terminate()
        if self.buzzer is not None:
            self.buzzer.off()


def crear_sonido_alarma():
    """Sirena de 1 s que alterna entre dos tonos (también la descarga la app)."""
    fs = 22050
    with wave.open(ARCHIVO_SONIDO, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        datos = bytearray()
        for i in range(fs):
            t = i / fs
            freq = 1000 if int(t * 4) % 2 == 0 else 750
            datos += struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * t)))
        w.writeframes(bytes(datos))


# ---------------------------------------------------------------
# Módulo de visión: cámara oficial, USB o simulada
# ---------------------------------------------------------------
class Camara:
    def __init__(self, simular=False):
        self.picam = None
        self.cap = None
        self.simular = simular
        self.t0 = time.time()
        if simular:
            print("📷 Cámara simulada")
            return
        try:
            from picamera2 import Picamera2
            self.picam = Picamera2()
            self.picam.configure(self.picam.create_preview_configuration(
                main={"format": "RGB888", "size": (ANCHO, ALTO)}))
            self.picam.start()
            print("📷 Usando cámara oficial (Picamera2)")
        except Exception:
            self.picam = None
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
            if not self.cap.isOpened():
                raise RuntimeError("No se pudo abrir ninguna cámara.")
            print("📷 Usando cámara USB (OpenCV)")

    def leer(self):
        if self.simular:
            t = time.time() - self.t0
            frame = np.full((ALTO, ANCHO, 3), (60, 45, 35), np.uint8)
            x = int(ANCHO / 2 + 250 * math.sin(t * 0.6))
            cv2.circle(frame, (x, ALTO // 2 + 40), 40, (200, 180, 120), -1)
            time.sleep(1 / 15)
            return True, frame
        if self.picam is not None:
            frame = self.picam.capture_array()
            if frame.ndim == 3 and frame.shape[2] == 4:      # XBGR -> 3 canales
                frame = frame[:, :, :3]
            if INVERTIR_COLORES:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # intercambia rojo y azul
            return True, frame
        return self.cap.read()

    def cerrar(self):
        if self.picam is not None:
            self.picam.stop()
        if self.cap is not None:
            self.cap.release()


# ---------------------------------------------------------------
# Módulo de sensado: PIR real o simulado
# ---------------------------------------------------------------
class SensorPIR:
    def __init__(self, simular=False):
        self.simular = simular
        self.t0 = time.time()
        if not simular:
            from gpiozero import MotionSensor
            # queue_len / threshold: subirlos lo hace menos sensible (ver informe)
            self.pir = MotionSensor(PIN_PIR, queue_len=1, threshold=0.5)

    def calibrar(self):
        if self.simular:
            return
        print("⏳ Calibrando sensor PIR (puede tardar hasta 60 s)...")
        self.pir.wait_for_no_motion()
        time.sleep(2)

    @property
    def movimiento(self):
        if self.simular:  # en simulación el "PIR" ve al objeto cuando está a la derecha
            return math.sin((time.time() - self.t0) * 0.6) > 0.3
        return self.pir.motion_detected


# ---------------------------------------------------------------
# Módulo de valla virtual: zona dibujada + detección de movimiento con la cámara
# ---------------------------------------------------------------
class VallaVirtual:
    def __init__(self):
        self.puntos = []                 # vértices del polígono (en píxeles)
        self.modo = "pir_y_valla"
        self.editando = False
        self.borrador = []
        self.mascara = None
        self.area_zona = ANCHO * ALTO
        self.fondo = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32,
                                                         detectShadows=False)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self.cuadros = 0
        self.objetos = []                # rectángulos de objetos en movimiento dentro de la valla
        self.ocupacion = 0.0
        self.ultimo_dentro = 0.0
        self.cargar()

    # --- Guardar / cargar ---
    def cargar(self):
        try:
            with open(ARCHIVO_VALLA, encoding="utf-8") as f:
                datos = json.load(f)
            self.puntos = [tuple(p) for p in datos.get("puntos", [])]
            if datos.get("modo") in MODOS:
                self.modo = datos["modo"]
            print(f"🧱 Valla virtual cargada: {len(self.puntos)} puntos · modo {MODOS[self.modo]}")
        except FileNotFoundError:
            print("🧱 Sin valla dibujada: se vigila toda la imagen (presiona 'z' para dibujarla)")
        except (ValueError, KeyError):
            print("⚠️  valla_virtual.json dañado: se vigila toda la imagen")
        self._actualizar_mascara()

    def guardar(self):
        with open(ARCHIVO_VALLA, "w", encoding="utf-8") as f:
            json.dump({"puntos": self.puntos, "modo": self.modo}, f, indent=2)

    def _actualizar_mascara(self):
        self.mascara = np.zeros((ALTO, ANCHO), np.uint8)
        if len(self.puntos) >= 3:
            cv2.fillPoly(self.mascara, [np.array(self.puntos, np.int32)], 255)
        else:
            self.mascara[:] = 255
        self.area_zona = max(cv2.countNonZero(self.mascara), 1)

    def a_dict(self):
        return {"puntos": self.puntos, "modo": self.modo, "nombre_modo": MODOS[self.modo],
                "definida": len(self.puntos) >= 3}

    def definir(self, puntos=None, modo=None):
        if puntos is not None:
            self.puntos = [(int(x), int(y)) for x, y in puntos]
            self._actualizar_mascara()
        if modo in MODOS:
            self.modo = modo
        self.guardar()

    # --- Edición con el mouse ---
    def empezar_edicion(self):
        self.editando = True
        self.borrador = []
        print("✏️  Dibujando valla: clic izquierdo = agregar punto, clic derecho = borrar último,")
        print("    ENTER = guardar, 'c' = borrar valla (vigilar toda la imagen), 'z' = cancelar")

    def clic(self, evento, x, y, *_):
        if not self.editando:
            return
        if evento == cv2.EVENT_LBUTTONDOWN:
            self.borrador.append((x, y))
        elif evento == cv2.EVENT_RBUTTONDOWN and self.borrador:
            self.borrador.pop()

    def terminar_edicion(self, guardar=True):
        self.editando = False
        if guardar:
            if len(self.borrador) >= 3:
                self.definir(puntos=self.borrador)
                print(f"✅ Valla virtual guardada ({len(self.puntos)} puntos) en {ARCHIVO_VALLA}")
            else:
                print("⚠️  La valla necesita al menos 3 puntos. No se guardó.")
        else:
            print("↩️  Edición de valla cancelada")
        self.borrador = []

    def borrar(self):
        self.editando = False
        self.borrador = []
        self.definir(puntos=[])
        print("🧹 Valla borrada: se vigila toda la imagen")

    def siguiente_modo(self):
        claves = list(MODOS)
        self.definir(modo=claves[(claves.index(self.modo) + 1) % len(claves)])
        print(f"🔁 Modo de detección: {MODOS[self.modo]}")

    # --- Detección ---
    def analizar(self, frame):
        """Devuelve True si hay movimiento dentro de la valla (frame limpio, sin dibujos)."""
        gris = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)
        primer_plano = self.fondo.apply(gris)
        self.cuadros += 1
        if self.cuadros < 30:                    # el modelo de fondo aún está aprendiendo
            self.objetos, self.ocupacion = [], 0.0
            return False
        primer_plano = cv2.morphologyEx(primer_plano, cv2.MORPH_OPEN, self.kernel)
        primer_plano = cv2.dilate(primer_plano, self.kernel, iterations=2)
        dentro = cv2.bitwise_and(primer_plano, self.mascara)

        contornos, _ = cv2.findContours(dentro, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        self.objetos = [cv2.boundingRect(c) for c in contornos if cv2.contourArea(c) >= AREA_MINIMA]
        self.ocupacion = cv2.countNonZero(dentro) / self.area_zona
        if self.objetos and self.ocupacion >= UMBRAL_VALLA:
            self.ultimo_dentro = time.time()
        # Se mantiene "dentro" 1 s después de la última detección para evitar parpadeos
        return time.time() - self.ultimo_dentro < 1.0

    def decidir(self, pir, en_valla):
        if self.modo == "pir":
            return pir
        if self.modo == "valla":
            return en_valla
        return pir and en_valla

    # --- Dibujo ---
    def dibujar(self, frame, alerta):
        if self.editando:
            capa = frame.copy()
            if len(self.borrador) >= 3:
                cv2.fillPoly(capa, [np.array(self.borrador, np.int32)], (0, 200, 255))
                cv2.addWeighted(capa, 0.25, frame, 0.75, 0, frame)
            for i, p in enumerate(self.borrador):
                cv2.circle(frame, p, 5, (0, 200, 255), -1)
                if i:
                    cv2.line(frame, self.borrador[i - 1], p, (0, 200, 255), 2)
            if len(self.borrador) >= 3:
                cv2.line(frame, self.borrador[-1], self.borrador[0], (0, 200, 255), 1)
            texto(frame, "DIBUJANDO VALLA: clic=punto  der=borrar  ENTER=guardar  c=borrar  z=cancelar",
                  (10, 62), 0.45, (0, 200, 255))
            return

        color = (0, 0, 255) if alerta else (0, 220, 255)
        if len(self.puntos) >= 3:
            pts = np.array(self.puntos, np.int32)
            capa = frame.copy()
            cv2.fillPoly(capa, [pts], color)
            cv2.addWeighted(capa, 0.18 if not alerta else 0.30, frame, 0.82 if not alerta else 0.70, 0, frame)
            cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
            x, y = min(p[0] for p in self.puntos), min(p[1] for p in self.puntos)
            texto(frame, "VALLA VIRTUAL", (x + 4, max(y - 8, 70)), 0.45, color)
        for (x, y, w, h) in self.objetos:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255) if alerta else (0, 165, 255), 2)
        texto(frame, f"Modo: {MODOS[self.modo]}", (20, 62), 0.45, (255, 255, 255))


# ---------------------------------------------------------------
# Estado compartido entre el hilo principal y el servidor
# ---------------------------------------------------------------
class Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.listo = False
        self.armado = True
        self.movimiento = False
        self.en_valla = False
        self.alerta_activa = False
        self.silenciado = False
        self.total_alertas = 0
        self.ultimo_evento_id = 0
        self.ultima_foto = None
        self.inicio_alerta = None
        self.foto_manual = False

    def a_dict(self, valla=None):
        with self.lock:
            d = {
                "listo": self.listo,
                "armado": self.armado,
                "movimiento": self.movimiento,
                "en_valla": self.en_valla,
                "alerta": self.alerta_activa,
                "silenciado": self.silenciado,
                "total_alertas": self.total_alertas,
                "ultimo_evento_id": self.ultimo_evento_id,
                "ultima_foto": self.ultima_foto,
                "inicio_alerta": self.inicio_alerta,
                "total_capturas": len(listar_capturas()),
                "hora": datetime.now().strftime("%H:%M:%S"),
            }
        if valla is not None:
            d["valla"] = valla.a_dict()
        return d


def texto(frame, txt, pos, escala, color, grosor=1):
    cv2.putText(frame, txt, pos, cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), grosor + 1, cv2.LINE_AA)
    cv2.putText(frame, txt, pos, cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def registrar(txt):
    with open(ARCHIVO_REGISTRO, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {txt}\n")


def listar_capturas():
    return sorted((f for f in os.listdir(CARPETA_CAPTURAS) if f.endswith(".jpg")), reverse=True)


def fecha_desde_nombre(nombre):
    try:
        dt = datetime.strptime(nombre[8:23], "%Y%m%d_%H%M%S")
        return dt.strftime("%d-%m-%Y"), dt.strftime("%H:%M:%S")
    except ValueError:
        return "", ""


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------
# Módulo de comunicación: servidor web para la app
# ---------------------------------------------------------------
def crear_servidor(estado, valla):
    app = Flask(__name__)

    @app.after_request
    def cabeceras(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        if request.path.startswith("/api"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/")
    def inicio():
        return jsonify({"sistema": "Aegis Condor", "ok": True})

    @app.route("/video")
    def video():
        def generar():
            while True:
                with estado.lock:
                    jpg = estado.jpeg
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                time.sleep(0.1)
        return Response(generar(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/foto.jpg")
    def foto_actual():
        with estado.lock:
            jpg = estado.jpeg
        if not jpg:
            abort(503)
        return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.route("/alarma.wav")
    def sonido():
        return send_file(ARCHIVO_SONIDO, mimetype="audio/wav")

    @app.route("/api/estado")
    def api_estado():
        return jsonify(estado.a_dict(valla))

    @app.route("/api/eventos")
    def api_eventos():
        limite = request.args.get("limite", 50, type=int)
        eventos = []
        for f in listar_capturas()[:limite]:
            fecha, hora = fecha_desde_nombre(f)
            eventos.append({"archivo": f, "fecha": fecha, "hora": hora, "url": f"/capturas/{f}"})
        return jsonify(eventos)

    @app.route("/api/armado", methods=["POST"])
    def api_armado():
        datos = request.get_json(silent=True) or {}
        with estado.lock:
            estado.armado = bool(datos.get("armado", not estado.armado))
            armado = estado.armado
        print("🔒 Sistema ARMADO desde la app" if armado else "🔓 Sistema DESARMADO desde la app")
        registrar("Sistema armado (app)" if armado else "Sistema desarmado (app)")
        return jsonify(estado.a_dict(valla))

    @app.route("/api/valla", methods=["GET", "POST"])
    def api_valla():
        if request.method == "POST":
            datos = request.get_json(silent=True) or {}
            valla.definir(puntos=datos.get("puntos"), modo=datos.get("modo"))
            print(f"🧱 Valla actualizada desde la app · modo {MODOS[valla.modo]}")
        return jsonify(valla.a_dict())

    @app.route("/api/eventos/<nombre>", methods=["DELETE"])
    def api_borrar(nombre):
        if nombre not in listar_capturas():
            abort(404)
        os.remove(os.path.join(CARPETA_CAPTURAS, nombre))
        print(f"🗑️  Captura eliminada desde la app: {nombre}")
        return jsonify({"ok": True})

    @app.route("/capturas/<nombre>")
    def capturas(nombre):
        return send_from_directory(CARPETA_CAPTURAS, nombre)

    return app


def iniciar_servidor(estado, valla, puerto):
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = crear_servidor(estado, valla)
    hilo = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=puerto, threaded=True, use_reloader=False),
        daemon=True)
    hilo.start()


# ---------------------------------------------------------------
# Interfaz en pantalla
# ---------------------------------------------------------------
AYUDA = [
    "h  ocultar ayuda",
    "a  armar / desarmar",
    "z  dibujar valla virtual",
    "m  cambiar modo",
    "s  silenciar sirena",
    "f  foto manual",
    "q  salir",
]


def dibujar_interfaz(frame, estado_txt, color, total_alertas, silenciado):
    h, w = frame.shape[:2]
    texto(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (10, h - 15), 0.5, (255, 255, 255))
    texto(frame, estado_txt, (20, 35), 0.7, color, 2)
    texto(frame, f"Alertas: {total_alertas}" + ("  [SILENCIO]" if silenciado else ""),
          (w - 230 if silenciado else w - 130, h - 15), 0.5, (255, 255, 255))
    cv2.circle(frame, (w - 25, 25), 10, color, -1)


def dibujar_alerta(frame):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 14)
    txt = "! ALERTA: PERSONA EN ZONA !"
    (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_DUPLEX, 0.9, 2)
    x, y = (w - tw) // 2, h // 2
    cv2.rectangle(frame, (x - 15, y - th - 15), (x + tw + 15, y + 15), (0, 0, 200), -1)
    cv2.putText(frame, txt, (x, y), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)


def dibujar_ayuda(frame):
    x, y0 = frame.shape[1] - 230, 50
    capa = frame.copy()
    cv2.rectangle(capa, (x - 10, y0 - 20), (frame.shape[1] - 10, y0 + 22 * len(AYUDA)), (0, 0, 0), -1)
    cv2.addWeighted(capa, 0.6, frame, 0.4, 0, frame)
    for i, linea in enumerate(AYUDA):
        texto(frame, linea, (x, y0 + i * 22), 0.5, (255, 255, 255))


# ---------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Aegis Condor")
    parser.add_argument("--simular", action="store_true", help="Sin sensor ni cámara (pruebas)")
    parser.add_argument("--puerto", type=int, default=PUERTO)
    parser.add_argument("--sin-ventana", action="store_true", help="No abrir la ventana de video")
    args = parser.parse_args()
    mostrar_ventana = HAY_PANTALLA and not args.sin_ventana

    print("🛡️  Aegis Condor - Sistema de seguridad en alturas")
    print(f"📁 Fotos: {CARPETA_CAPTURAS}")
    print(f"📝 Registro: {ARCHIVO_REGISTRO}")

    estado = Estado()
    sensor = SensorPIR(args.simular)
    alarma = Alarma(args.simular)
    camara = Camara(args.simular)
    valla = VallaVirtual()

    iniciar_servidor(estado, valla, args.puerto)
    ip = ip_local()
    print("\n" + "=" * 52)
    print(f"📱 IP para la app del celular: {ip}")
    print(f"   (prueba en el navegador: http://{ip}:{args.puerto}/api/estado)")
    print("   El celular debe estar en la misma red Wi-Fi.")
    print("=" * 52 + "\n")

    calibrado = threading.Event()

    def calibrar():
        sensor.calibrar()
        with estado.lock:
            estado.listo = True
        calibrado.set()
        print("✅ PIR listo. Vigilando...")
        print("   Teclas: h=ayuda  a=armar/desarmar  z=dibujar valla  m=modo  s=silenciar  f=foto  q=salir\n")

    threading.Thread(target=calibrar, daemon=True).start()
    registrar(f"Sistema iniciado (modo {MODOS[valla.modo]})")

    if mostrar_ventana:
        cv2.namedWindow(VENTANA)
        cv2.setMouseCallback(VENTANA, valla.clic)

    ultimo_tiempo_foto = 0.0
    ultimo_movimiento = 0.0
    mostrar_ayuda = False
    ultimo_en_valla = False

    try:
        while True:
            ret, frame = camara.leer()
            if not ret:
                print("❌ Error: no se puede obtener imagen de la cámara.")
                break

            ahora = time.time()
            with estado.lock:
                armado = estado.armado

            # --- Sensado: PIR + valla virtual (sobre la imagen limpia) ---
            pir = calibrado.is_set() and sensor.movimiento
            en_valla = valla.analizar(frame) if calibrado.is_set() else False
            intruso = calibrado.is_set() and not valla.editando and valla.decidir(pir, en_valla)

            if en_valla != ultimo_en_valla and calibrado.is_set():
                print("🧱 Movimiento DENTRO de la valla" if en_valla else "🧱 Valla despejada")
                ultimo_en_valla = en_valla

            # --- Lógica de alerta ---
            nueva_alerta = fin_alerta = False
            with estado.lock:
                estado.movimiento = pir
                estado.en_valla = en_valla
                if intruso and armado:
                    ultimo_movimiento = ahora
                    if not estado.alerta_activa:
                        estado.alerta_activa = True
                        estado.total_alertas += 1
                        estado.ultimo_evento_id += 1
                        estado.inicio_alerta = datetime.now().strftime("%H:%M:%S")
                        nueva_alerta = True
                elif estado.alerta_activa and (not armado or ahora - ultimo_movimiento > DURACION_ALERTA):
                    estado.alerta_activa = False
                    estado.silenciado = False
                    fin_alerta = True
                alerta_activa = estado.alerta_activa
                silenciado = estado.silenciado
                total = estado.total_alertas
                foto_manual, estado.foto_manual = estado.foto_manual, False

            if nueva_alerta:
                motivo = {"pir": "PIR", "valla": "valla virtual", "pir_y_valla": "PIR + valla virtual"}[valla.modo]
                print(f"🚨 ALERTA #{total}: persona en zona ({motivo}) a las {estado.inicio_alerta}")
                registrar(f"ALERTA #{total}: persona en zona ({motivo})")
            if fin_alerta:
                alarma.detener()
                print("✅ Alerta finalizada: zona despejada")
                registrar("Alerta finalizada")
            if alerta_activa and not silenciado:
                alarma.sonar()

            # --- Interfaz ---
            if not calibrado.is_set():
                txt, color = "CALIBRANDO SENSOR", (0, 200, 255)
            elif not armado:
                txt, color = "SISTEMA DESARMADO", (160, 160, 160)
            elif alerta_activa:
                txt, color = "MOVIMIENTO DETECTADO", (0, 0, 255)
            else:
                txt, color = "SIN MOVIMIENTO", (0, 255, 0)
            valla.dibujar(frame, alerta_activa)
            dibujar_interfaz(frame, txt, color, total, silenciado)

            # --- Foto de evidencia (automática o manual) ---
            if (intruso and armado and ahora - ultimo_tiempo_foto > COOLDOWN_FOTOS) or foto_manual:
                nombre = f"captura_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                if cv2.imwrite(os.path.join(CARPETA_CAPTURAS, nombre), frame):
                    with estado.lock:
                        estado.ultima_foto = nombre
                    print(f"📸 Foto {'manual ' if foto_manual else ''}guardada: {nombre}")
                    registrar(f"Foto {'manual ' if foto_manual else ''}guardada: {nombre}")
                else:
                    print(f"❌ Error al guardar: {nombre}")
                ultimo_tiempo_foto = ahora

            if alerta_activa and int(ahora * 2) % 2 == 0:
                dibujar_alerta(frame)

            # --- Compartir imagen con el servidor ---
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                with estado.lock:
                    estado.jpeg = buf.tobytes()

            # --- Ventana y teclado ---
            if mostrar_ventana:
                if mostrar_ayuda and not valla.editando:
                    dibujar_ayuda(frame)
                cv2.imshow(VENTANA, frame)
                tecla = cv2.waitKey(1) & 0xFF

                if valla.editando:
                    if tecla in (13, 10):                 # ENTER
                        valla.terminar_edicion(guardar=True)
                        registrar("Valla virtual modificada")
                    elif tecla == ord('c'):
                        valla.borrar()
                        registrar("Valla virtual borrada")
                    elif tecla in (ord('z'), 27):
                        valla.terminar_edicion(guardar=False)
                    continue

                if tecla in (ord('q'), 27):
                    break
                elif tecla == ord('h'):
                    mostrar_ayuda = not mostrar_ayuda
                elif tecla == ord('a'):
                    with estado.lock:
                        estado.armado = not estado.armado
                        armado = estado.armado
                    print("🔒 Sistema ARMADO" if armado else "🔓 Sistema DESARMADO")
                    registrar("Sistema armado (teclado)" if armado else "Sistema desarmado (teclado)")
                elif tecla == ord('z'):
                    valla.empezar_edicion()
                elif tecla == ord('m'):
                    valla.siguiente_modo()
                    registrar(f"Modo cambiado a {MODOS[valla.modo]}")
                elif tecla == ord('s'):
                    with estado.lock:
                        if estado.alerta_activa:
                            estado.silenciado = True
                    alarma.detener()
                    print("🔇 Sirena silenciada (la alerta sigue registrándose)")
                elif tecla == ord('f'):
                    with estado.lock:
                        estado.foto_manual = True
            elif not args.simular:
                time.sleep(0.01)

    except KeyboardInterrupt:
        pass
    finally:
        alarma.detener()
        camara.cerrar()
        if mostrar_ventana:
            cv2.destroyAllWindows()
        registrar(f"Sistema detenido (alertas: {estado.total_alertas})")
        print(f"\nPrograma finalizado. Total de alertas: {estado.total_alertas}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        input("Presiona Enter para cerrar...")
