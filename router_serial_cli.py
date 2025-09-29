import re
import time
import serial  # pyserial

# Detecta prompt típico de Cisco (ej: Router> o R1#)
PROMPT_RE = re.compile(r"[^\r\n]{1,64}[>#]\s?$")

class RouterCisco:
    def __init__(self, puerto="COM10", baudios=9600, timeout=1):
        self.puerto = puerto
        self.baudios = baudios
        self.timeout = timeout
        self.conexion = None

    def conectar(self):
        try:
            self.conexion = serial.Serial(
                port=self.puerto,
                baudrate=self.baudios,
                timeout=self.timeout
            )
            time.sleep(2)
            print(f"[+] Conectado a {self.puerto} a {self.baudios} bps.")
        except serial.SerialException as e:
            print(f"[!] Error al abrir {self.puerto}: {e}")
            self.conexion = None

    def _leer_hasta_prompt(self, espera_max=3.0):
        """Lee datos hasta detectar el prompt o agotar tiempo."""
        if not self.conexion or not self.conexion.is_open:
            return ""
        fin = time.time() + espera_max
        buffer = bytearray()
        while time.time() < fin:
            chunk = self.conexion.read(self.conexion.in_waiting or 1)
            if chunk:
                buffer += chunk
                # ¿ya terminó en prompt?
                ult_linea = buffer.decode("utf-8", errors="ignore").splitlines()[-1:] or [""]
                if PROMPT_RE.search(ult_linea[0]):
                    break
            else:
                time.sleep(0.05)
        return buffer.decode("utf-8", errors="ignore")

    def enviar_comando(self, comando: str):
        """
        Envía el comando y devuelve salida completa (eco + respuesta + nuevo prompt).
        """
        if not self.conexion or not self.conexion.is_open:
            print("[!] No hay conexión abierta.")
            return ""

        try:
            # Enviar comando
            self.conexion.write((comando + "\r\n").encode("utf-8", errors="ignore"))
            # Leer salida
            salida = self._leer_hasta_prompt(espera_max=3.0)
            return salida
        except serial.SerialException as e:
            return f"[!] Error de E/S serial: {e}"

    def cerrar(self):
        if self.conexion and self.conexion.is_open:
            self.conexion.close()
            print("[+] Conexión cerrada.")

def main():
    router = RouterCisco(puerto="COM10", baudios=9600, timeout=1)
    router.conectar()
    if not router.conexion:
        return

    print("\n[ Consola interactiva Cisco ]")
    print("Escribe comandos para el router")
    print(" Usa 'quit' o 'salir' para terminar el programa (el comando 'exit' va al router)\n")

    try:
        while True:
            cmd = input("> ").strip()
            if cmd.lower() in ("quit", "salir"):
                break
            respuesta = router.enviar_comando(cmd)
            if respuesta:
                print(respuesta, end="" if respuesta.endswith("\n") else "\n")
    finally:
        router.cerrar()

if __name__ == "__main__":
    main()
