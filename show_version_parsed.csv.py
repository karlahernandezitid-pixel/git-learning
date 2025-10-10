import io
import re
import time
import csv
from pathlib import Path

# ====== DEPENDENCIAS ======
# pip install textfsm pyserial
import textfsm
import serial
import serial.tools.list_ports

# ====== CONFIG ======
BAUDRATES = [9600, 115200]
SERIAL_TIMEOUT = 1.2         # segundos para lecturas no bloqueantes
BOOT_SETTLE = 2.0            # espera al abrir el puerto
READ_WINDOW_S = 5.0          # ventana total de lectura tras enviar comando
CSV_NAME = "show_version_parsed.csv"
FALLBACK_TXT = "show_version.txt"  # si el serial falla, intentamos parsear este archivo

# ====== PLANTILLA TEXTFSM (EMBEBIDA) ======
TPL_STRING = r"""
# Plantilla TextFSM para 'show version' (Cisco IOS / IOS-XE)
# Extrae: HOSTNAME, VERSION, UPTIME

Value Filldown HOSTNAME (\S+)
Value Filldown VERSION ([0-9A-Za-z.\-()+]+)
Value Filldown UPTIME (.+)

Start
  ^${HOSTNAME}\s+uptime is\s+${UPTIME} -> Continue
  ^Cisco IOS Software.*, Version\s+${VERSION}(?:,|$) -> Record
  ^Cisco IOS XE Software.*, Version\s+${VERSION}(?:,|$) -> Record
  ^IOS \(tm\).*, Version\s+${VERSION}(?:,|$) -> Record
  ^.* -> Continue

EOF
  ^ -> Record
"""

def pick_serial_port():
    """
    Selecciona automáticamente un puerto que parezca USB-Serial.
    Preferimos los que tengan 'USB', 'Prolific', 'Silicon', 'FTDI', 'CH340', 'Manhattan' en la descripción.
    Si no hay coincidencias, tomamos el primero disponible.
    """
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None

    keywords = ("USB", "Prolific", "Silicon", "FTDI", "CH340", "Manhattan", "UART")
    # try to pick a likely USB-Serial
    for p in ports:
        desc = f"{p.description} {p.manufacturer or ''} {p.hwid or ''}"
        if any(k.lower() in desc.lower() for k in keywords):
            return p.device
    # fallback: first port
    return ports[0].device

def serial_read_all(ser, duration_s=READ_WINDOW_S):
    """
    Lee todo lo que salga por el puerto durante 'duration_s' segundos.
    """
    end_t = time.time() + duration_s
    buff = bytearray()
    while time.time() < end_t:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buff += chunk
        else:
            time.sleep(0.05)
    try:
        return buff.decode(errors="ignore")
    except Exception:
        return buff.decode("latin-1", errors="ignore")

def try_get_show_version():
    """
    Intenta:
      1) Detectar un puerto
      2) Abrirlo a cada baudrate
      3) Enviar 'terminal length 0' y 'show version'
      4) Devolver la salida de show version (str)
    Si falla todo, retorna None.
    """
    port = pick_serial_port()
    if not port:
        return None

    for baud in BAUDRATES:
        try:
            with serial.Serial(port=port, baudrate=baud, timeout=SERIAL_TIMEOUT) as ser:
                # dar tiempo a que la consola despierte
                time.sleep(BOOT_SETTLE)

                # "despertar" la consola, limpiar paginación y pedir show version
                ser.write(b"\r\n")
                time.sleep(0.3)
                _ = serial_read_all(ser, 1.0)

                ser.write(b"terminal length 0\r\n")
                time.sleep(0.2)
                _ = serial_read_all(ser, 0.8)

                ser.write(b"show version\r\n")
                output = serial_read_all(ser, READ_WINDOW_S)

                # algunas consolas tardan más; si está corto, espera otro poco
                if len(output.strip()) < 50:
                    time.sleep(1.5)
                    output += serial_read_all(ser, 2.5)

                # limpieza básica de más prompts
                output = output.replace("\r", "")
                # intenta recortar desde la línea del comando
                m = re.search(r"(?im)^\s*show version\s*$", output)
                if m:
                    output = output[m.end():]

                if "version" in output.lower() or "uptime" in output.lower():
                    return output
        except Exception:
            # probamos con otro baudrate o fallamos
            continue
    return None

def parse_show_version_text(text):
    """
    Parsea el texto con la plantilla embebida y retorna (headers, rows).
    """
    with io.StringIO(TPL_STRING) as tpl:
        fsm = textfsm.TextFSM(tpl)
        rows = fsm.ParseText(text)
    return fsm.header, rows

def save_csv(headers, rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)

def main():
    base = Path.cwd()
    csv_path = base / CSV_NAME

    # 1) Intento por SERIAL (automático)
    sv_text = try_get_show_version()

    # 2) Fallback por archivo
    if sv_text is None:
        txt_file = base / FALLBACK_TXT
        if txt_file.exists():
            sv_text = txt_file.read_text(encoding="utf-8", errors="ignore")
        else:
            print("⚠️ No se pudo leer por consola serial y tampoco existe", FALLBACK_TXT)
            print("   Opciones:")
            print("   - Conecta el cable consola y vuelve a correr el script.")
            print("   - O crea un archivo 'show_version.txt' con la salida del comando y vuelve a correr.")
            return

    # 3) Parseo con TextFSM
    try:
        headers, rows = parse_show_version_text(sv_text)
    except Exception as e:
        print("❌ Error al parsear con TextFSM:", e)
        # Guarda copia del texto para depurar
        (base / "DEBUG_show_version_raw.txt").write_text(sv_text, encoding="utf-8", errors="ignore")
        print("   Se guardó DEBUG_show_version_raw.txt para que me lo mandes y ajusto la plantilla.")
        return

    if not rows:
        print("⚠️ No se extrajo ningún registro. Guardo la salida cruda para revisión.")
        (base / "DEBUG_show_version_raw.txt").write_text(sv_text, encoding="utf-8", errors="ignore")
        return

    # 4) Guardar CSV
    save_csv(headers, rows, csv_path)

    print("✅ Listo.")
    print("Encabezados:", headers)
    for r in rows:
        print(r)
    print(f"📄 CSV generado: {csv_path.resolve()}")

if __name__ == "__main__":
    main()
