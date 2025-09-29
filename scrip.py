import serial
import time
import pandas as pd
import os
import re

# 🔹 Limpiar pantalla según el SO
def limpiar_consola():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

# 🔹 Enviar comando al router
def ejecutar_comando(conexion, instruccion, pausa=1):
    conexion.write((instruccion + "\r\n").encode())  # CRLF
    time.sleep(pausa)
    salida = conexion.read(conexion.in_waiting).decode(errors="ignore")
    return salida

# 🔹 Obtener número de serie desde "show inventory"
def buscar_serial(canal_serial):
    ejecutar_comando(canal_serial, "terminal length 0")  # evitar paginación
    respuesta_inv = ejecutar_comando(canal_serial, "show inventory", pausa=2)
    hallazgo = re.search(r"SN:\s*([A-Z0-9]+)", respuesta_inv)
    if hallazgo:
        return hallazgo.group(1)
    return None

# 🔹 Configuración de dispositivo
def aplicar_config(puerto, alias, usuario, clave, dominio):
    try:
        canal = serial.Serial(puerto, baudrate=9600, timeout=1)
        time.sleep(2)
        print(f"\n🔗 Conectado al dispositivo en {puerto} ({alias})")

        num_serie = buscar_serial(canal)
        if not num_serie:
            print("⚠ No se pudo obtener el número de serie. Saltando configuración.")
            canal.close()
            return False

        if alias[1:] != num_serie:
            print(f"⚠ La serie del dispositivo ({num_serie}) no coincide con la del CSV ({alias[1:]}). Saltando configuración.")
            canal.close()
            return False

        ejecutar_comando(canal, "enable")
        ejecutar_comando(canal, "configure terminal")
        ejecutar_comando(canal, f"hostname {alias}")
        ejecutar_comando(canal, f"username {usuario} privilege 15 secret {clave}")
        ejecutar_comando(canal, f"ip domain-name {dominio}")
        ejecutar_comando(canal, "crypto key generate rsa modulus 1024", pausa=3)
        ejecutar_comando(canal, "line vty 0 4")
        ejecutar_comando(canal, "login local")
        ejecutar_comando(canal, "transport input ssh")
        ejecutar_comando(canal, "transport output ssh")
        ejecutar_comando(canal, "exit")
        ejecutar_comando(canal, "ip ssh version 2")
        ejecutar_comando(canal, "end")
        ejecutar_comando(canal, "write memory", pausa=2)

        print(f"✅ Configuración aplicada correctamente en {alias}.")
        canal.close()
        return True

    except Exception as e:
        print(f"❌ Error al configurar el dispositivo {alias}: {e}")
        return False

# 🔹 Menú principal
def ver_opciones():
    limpiar_consola()
    print("=== MENÚ PRINCIPAL ===")
    print("1. Mandar comandos manualmente")
    print("2. Hacer configuraciones iniciales desde CSV")
    print("0. Salir")

# 🔹 Menú de comandos manuales
def modo_interactivo():
    puerto_usr = input("🔌 Ingresa el puerto serial (ej. COM3): ")
    try:
        sesion = serial.Serial(puerto_usr, baudrate=9600, timeout=1)
        time.sleep(2)
        print(f"\n✅ Conectado al dispositivo en {puerto_usr}")
        while True:
            cmd_linea = input("📥 Ingresa el comando (o 'exit' para salir): ")
            if cmd_linea.lower() == "exit":
                break
            respuesta = ejecutar_comando(sesion, cmd_linea, pausa=2)
            print(f"\n📤 Respuesta:\n{respuesta}")
        sesion.close()
    except Exception as e:
        print(f"❌ Error al conectar: {e}")
    input("Presione ENTER para volver al menú...")

# 🔹 Flujo de configuración inicial
def proceso_desde_csv():
    limpiar_consola()
    try:
        # Ruta del archivo CSV actualizada para el nuevo usuario
        ruta_archivo = r"C:\Users\lucer\OneDrive\Documentos\Gip\Data.csv"
        tabla_datos = pd.read_csv(ruta_archivo)
        
    except FileNotFoundError:
        print("\n❌ ERROR: No se encontró el archivo 'Data.csv' en la ruta especificada.")
        print(f"Asegúrate de que el archivo exista en: {ruta_archivo}")
        input("Presione ENTER para volver al menú...")
        return

    print("\n📂 Dispositivos encontrados en el archivo:")
    print(tabla_datos)

    Aliases = [str(d).strip()[0] + str(s).strip() for d, s in zip(tabla_datos['Device'], tabla_datos['Serie'])]
    cola_de_trabajo = [(p, h, u, pas, dom) for p, u, pas, dom, h in zip(tabla_datos['Port'], tabla_datos['User'], tabla_datos['Password'], tabla_datos['Ip-domain'], Aliases)]

    print("\n📋 Lista de dispositivos y sus configuraciones:")
    for tarea in cola_de_trabajo:
        print(tarea)
    input("Presione ENTER para continuar...")

    equipos_listos = []
    equipos_fallidos = []

    for contador, (p, h, u, pas, dom) in enumerate(cola_de_trabajo, start=1):
        limpiar_consola()
        print(f"\n➡ Conecte ahora el dispositivo {contador}: {h} en el puerto {p}")
        input("Presione ENTER cuando el dispositivo esté conectado...")
        resultado_ok = aplicar_config(p, h, u, pas, dom)
        if resultado_ok:
            equipos_listos.append(h)
        else:
            equipos_fallidos.append(h)
        print("=================================================")
        input("Presione ENTER para continuar...")

    limpiar_consola()
    print("📊 Resumen de la configuración:")
    print(f"✅ Dispositivos configurados ({len(equipos_listos)}): {equipos_listos}")
    print(f"⚠ Dispositivos saltados ({len(equipos_fallidos)}): {equipos_fallidos}")
    input("Presione ENTER para volver al menú...")

# 🔹 Ejecutar menú
if __name__ == "__main__":
    while True:
        ver_opciones()
        eleccion = input("Selecciona una opción: ")
        if eleccion == "1":
            modo_interactivo()
        elif eleccion == "2":
            proceso_desde_csv()
        elif eleccion == "0":
            print("👋 Saliendo del programa...")
            break
        else:
            print("❌ Opción inválida.")
            input("Presione ENTER para continuar...")
