import sys, io, os, csv, time
import textfsm

# Forzar UTF-8 en Windows (bordes)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# === Plantilla TextFSM (con $ escapados como $$) ===
TPL = r"""# TPL para 'show ip interface brief' (Cisco IOS/IOS-XE)
Value Required INTERFACE (\S+)
Value IPADDR (\S+)
Value OK (\S+)
Value METHOD (\S+)
Value STATUS (administratively down|up|down|deleted|reset|testing|unknown)
Value PROTOCOL (up|down)

Start
  ^\s*Interface\s+IP[\- ]Address\s+OK\?\s+Method\s+Status\s+Protocol\s*$$ -> Continue
  ^${INTERFACE}\s+${IPADDR}\s+${OK}\s+${METHOD}\s+${STATUS}\s+${PROTOCOL}\s*$$ -> Record
  ^.* -> Continue
"""

def print_table(headers, rows):
    w = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            w[i] = max(w[i], len(str(c)))

    def line(l, m, r, fill='─'):
        return l + m.join(fill * (x + 2) for x in w) + r

    def row(vals):
        return '│' + '│'.join(f' {str(v).ljust(w[i])} ' for i, v in enumerate(vals)) + '│'

    print(line('┌', '┬', '┐'))
    print(row(headers))
    print(line('├', '┼', '┤'))
    for r in rows:
        print(row(r))
    print(line('└', '┴', '┘'))

def parse_text(text):
    tpl = io.StringIO(TPL.replace("\r", ""))
    fsm = textfsm.TextFSM(tpl)
    rows = fsm.ParseText(text or "")
    return fsm.header, rows

def save_csv(headers, rows, path="show_ip_int_brief.csv"):
    # comportamiento original: sobrescribe
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return os.path.abspath(path)

# ---- NUEVO: guardar anexando (para modo manual) ----
def save_csv_append(headers, rows, path="show_ip_int_brief.csv"):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(headers)
        w.writerows(rows)
    return os.path.abspath(path)

def try_serial():
    try:
        import serial, serial.tools.list_ports
    except ImportError:
        return None
    # Elegir un puerto USB-Serial si hay
    ports = list(serial.tools.list_ports.comports())
    port = None
    for p in ports:
        desc = f"{p.description} {p.manufacturer or ''} {p.hwid or ''}".lower()
        if any(k in desc for k in ("usb", "ftdi", "prolific", "ch340", "uart", "silicon", "manhattan")):
            port = p.device
            break
    if not port and ports:
        port = ports[0].device
    if not port:
        return None

    try:
        import serial
        with serial.Serial(port=port, baudrate=9600, timeout=1) as ser:
            time.sleep(1.8)
            ser.write(b"terminal length 0\r\n"); time.sleep(0.4); _ = ser.read(ser.in_waiting or 1)
            ser.write(b"show ip interface brief\r\n"); time.sleep(2.0)
            out = ser.read(ser.in_waiting or 1).decode(errors="ignore")
            time.sleep(0.8)
            out += ser.read(ser.in_waiting or 1).decode(errors="ignore")
            return out if out.strip() else None
    except Exception:
        return None

def try_file(path="show_ip_int_brief.txt"):
    return open(path, "r", encoding="utf-8", errors="ignore").read() if os.path.exists(path) else None

# ------- NUEVO: helpers para modo manual -------
def detect_port():
    """Devuelve un puerto COM probable o None."""
    try:
        import serial.tools.list_ports as lp
    except Exception:
        return None
    ports = list(lp.comports())
    for p in ports:
        desc = f"{p.description} {p.manufacturer or ''} {p.hwid or ''}".lower()
        if any(k in desc for k in ("usb", "ftdi", "prolific", "ch340", "uart", "silicon", "manhattan")):
            return p.device
    return ports[0].device if ports else None

def send_and_read(ser, cmd, wait=1.0):
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    data = ser.read(ser.in_waiting or 1).decode(errors="ignore")
    time.sleep(0.3)
    data += ser.read(ser.in_waiting or 1).decode(errors="ignore")
    return data

def is_show_ip_int_brief(cmd: str) -> bool:
    c = " ".join(cmd.strip().lower().split())
    return c in {
        "show ip interface brief",
        "show ip int brief",
        "sh ip interface brief",
        "sh ip int br",
        "sh ip int bri",
        "sho ip int br",
    }

def manual_commands_mode():
    """Modo interactivo: no toca el flujo principal."""
    try:
        import serial
    except Exception:
        print("\n(No tienes pyserial instalado para modo manual)")
        return

    port = detect_port() or input("\nPuerto COM (ej. COM13): ").strip()
    try:
        with serial.Serial(port=port, baudrate=9600, timeout=1) as ser:
            time.sleep(1.5)
            send_and_read(ser, "terminal length 0", 0.3)
            print(f"\n🔗 Modo manual en {port}. Escribe ':salir' para terminar.\n")
            while True:
                cmd = input("> ").strip()
                if cmd == "" or cmd.lower() == ":salir":
                    break

                out = send_and_read(ser, cmd, wait=2.0)

                if is_show_ip_int_brief(cmd):
                    # Parsear y tabla
                    headers, rows = parse_text(out)
                    if rows:
                        print("\n📊 Resultado (TextFSM):\n")
                        print_table(headers, rows)
                        path = save_csv_append(headers, rows)  # anexa, no borra
                        print(f"\n💾 CSV actualizado: {path}\n")
                    else:
                        print("\n(No se pudo parsear con TextFSM, salida cruda):\n")
                        print(out)
                else:
                    # Cualquier otro comando: salida cruda
                    print("\n--- Salida ---\n")
                    print(out)
                    print("\n--------------\n")

    except Exception as e:
        print(f"\nNo se pudo abrir el puerto: {e}\n")

def main():
    # 1) intentar por serial, 2) fallback a archivo
    text = try_serial() or try_file()
    if not text:
        print("⚠️ No pude leer por serial ni encontré 'show_ip_int_brief.txt'.")
        print("   Conecta el cable consola o crea ese TXT con la salida y vuelve a correr.")
        return

    try:
        headers, rows = parse_text(text)
    except Exception as e:
        print("❌ Error al parsear (TPL):", e)
        print("\nSalida cruda:\n", text)
        return

    if not rows:
        print("⚠️ No se obtuvieron filas. Salida cruda:\n")
        print(text)
        return

    print("\n📊 Resultado (TextFSM):\n")
    print_table(headers, rows)
    out_csv = save_csv(headers, rows)  # comportamiento original
    print(f"\n💾 CSV guardado: {out_csv}")

    # ---- NUEVO: preguntar si quieres entrar al modo manual ----
    ans = input("\n¿Entrar a modo de comandos manuales? (s/n): ").strip().lower()
    if ans == "s":
        manual_commands_mode()

if __name__ == "__main__":
    main()
