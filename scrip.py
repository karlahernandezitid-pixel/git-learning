import serial
import time
import pandas as pd
import os
import re

# =============== Utilidades de consola ===============

def limpiar_pantalla_consola():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

def esperar_lectura(s, pausa=1.0):
    """Pequeña espera y lectura robusta del buffer."""
    time.sleep(pausa)
    bytes_disp = max(getattr(s, "in_waiting", 0), 0)
    if bytes_disp:
        try:
            return s.read(bytes_disp).decode(errors="ignore")
        except Exception:
            return ""
    return ""

def enviar_comando_al_equipo(puerto_serial, comando_para_enviar, retraso=1.0):
    """Envía comando con CRLF, espera, y regresa la salida disponible."""
    # drenar buffer previo
    _ = esperar_lectura(puerto_serial, pausa=0.2)
    puerto_serial.write((comando_para_enviar + "\r\n").encode())
    return esperar_lectura(puerto_serial, pausa=retraso)

# =============== Descubrimiento del equipo ===============

def obtener_numero_de_serie(conexion_serial):
    """Intenta leer SN de 'show inventory'."""
    enviar_comando_al_equipo(conexion_serial, "terminal length 0")
    salida_inventario = enviar_comando_al_equipo(conexion_serial, "show inventory", retraso=2)
    # Ejemplos: SN: FGL1234ABC
    m = re.search(r"SN:\s*([A-Z0-9]+)", salida_inventario, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper().strip()
    return None

# =============== Config de un dispositivo ===============

def configurar_dispositivo_individual(puerto_com, nombre_host, nombre_usuario, clave_secreta, nombre_dominio, serie_esperada=None):
    """
    Aplica configuración básica al equipo.
    - nombre_host: ahora viene DIRECTO de 'Device' en el CSV.
    - serie_esperada: se valida contra el SN detectado (si viene en CSV).
    """
    try:
        conexion_activa = serial.Serial(port=puerto_com, baudrate=9600, timeout=1)
        time.sleep(2)  # ventana para que levante consola
        print(f"\n🔗 Conectado en {puerto_com}  |  Host objetivo: {nombre_host}")

        serial_obtenido = obtener_numero_de_serie(conexion_activa)
        if not serial_obtenido:
            print("⚠️  No se pudo obtener el número de serie del equipo. Omitiendo.")
            conexion_activa.close()
            return False

        if serie_esperada:
            serie_esperada = str(serie_esperada).strip().upper()
            if serie_esperada != serial_obtenido:
                print(f"❌ Serie detectada '{serial_obtenido}' ≠ serie CSV '{serie_esperada}'. Omitiendo este equipo.")
                conexion_activa.close()
                return False

        # Enviar configuración básica
        enviar_comando_al_equipo(conexion_activa, "enable")
        enviar_comando_al_equipo(conexion_activa, "configure terminal")
        enviar_comando_al_equipo(conexion_activa, f"hostname {nombre_host}")
        enviar_comando_al_equipo(conexion_activa, f"username {nombre_usuario} privilege 15 secret {clave_secreta}")
        enviar_comando_al_equipo(conexion_activa, f"ip domain-name {nombre_dominio}")
        enviar_comando_al_equipo(conexion_activa, "crypto key generate rsa modulus 1024", retraso=3)
        enviar_comando_al_equipo(conexion_activa, "line vty 0 4")
        enviar_comando_al_equipo(conexion_activa, "login local")
        enviar_comando_al_equipo(conexion_activa, "transport input ssh")
        enviar_comando_al_equipo(conexion_activa, "transport output ssh")
        enviar_comando_al_equipo(conexion_activa, "exit")
        enviar_comando_al_equipo(conexion_activa, "ip ssh version 2")
        enviar_comando_al_equipo(conexion_activa, "end")
        enviar_comando_al_equipo(conexion_activa, "write memory", retraso=2)

        print(f"✅ Configuración aplicada en '{nombre_host}'.")
        conexion_activa.close()
        return True

    except Exception as e:
        print(f"❌ No se pudo configurar '{nombre_host}': {e}")
        return False

# =============== Menús ===============

def presentar_menu_principal():
    limpiar_pantalla_consola()
    print("=== MENÚ ===")
    print("1) Comandos manuales")
    print("2) Configuración por CSV")
    print("0) Salir")

def menu_de_comandos_manuales():
    print("\n💡 Escribe ':volver' para regresar al menú principal.")
    puerto_de_conexion = input("¿En qué puerto estás conectado? -> ").strip()
    try:
        sesion_serial = serial.Serial(puerto_de_conexion, baudrate=9600, timeout=1)
        time.sleep(2)
        print(f"\nConectado en {puerto_de_conexion}")
        while True:
            comando = input("Ingresa el comando: ").strip()
            if comando == ":volver":
                break
            # Enviamos TAL CUAL (si escribes 'exit', se manda al router; no cierra el programa)
            salida = enviar_comando_al_equipo(sesion_serial, comando, retraso=2)
            print(f"\n--- Salida ---\n{salida}\n--------------")
        sesion_serial.close()
    except Exception as e:
        print(f"No se pudo conectar: {e}")
    input("ENTER para volver...")

# =============== Flujo por CSV ===============

def abrir_csv_dispositivos():
    # Intenta varias rutas comunes; ajusta esta lista a tu entorno
    posibles_rutas = [
        r"C:\Users\lucer\OneDrive\Documentos\Gip\DATA.csv",
        r"C:\Users\jesus\OneDrive\Documentos\CODIGOS\clase_ebueno\DATA.csv",
        r"/mnt/data/DATA.csv",
    ]
    for ruta in posibles_rutas:
        try:
            if os.path.exists(ruta):
                return pd.read_csv(ruta), ruta
        except Exception:
            pass
    raise FileNotFoundError("No se encontró DATA.csv en las rutas conocidas. Edita 'posibles_rutas' en el script.")

def flujo_de_configuracion_con_csv():
    limpiar_pantalla_consola()
    try:
        dataframe_dispositivos, ruta_csv = abrir_csv_dispositivos()
    except FileNotFoundError as e:
        print("\n❌", e)
        input("ENTER para volver al menú...")
        return

    print(f"\nArchivo CSV cargado desde: {ruta_csv}")
    print(dataframe_dispositivos)

    # === Cambio clave: hostname sale DIRECTO de 'Device' ===
    # Limpiamos strings y preparamos campos
    devices = dataframe_dispositivos['Device'].astype(str).str.strip()
    puertos = dataframe_dispositivos['Port'].astype(str).str.strip()
    usuarios = dataframe_dispositivos['User'].astype(str).str.strip()
    claves = dataframe_dispositivos['Password'].astype(str).str.strip()
    dominios = dataframe_dispositivos['Ip-domain'].astype(str).str.strip()
    series = dataframe_dispositivos['Serie'].astype(str).str.strip()

    # Lista de trabajo: (port, host(Device), user, pass, domain, serie)
    lista_completa_dispositivos = list(zip(puertos, devices, usuarios, claves, dominios, series))

    print("\nDispositivos detectados (Port, Host(Device), User, ****, Domain, Serie):")
    for p, h, u, _, d, s in lista_completa_dispositivos:
        print(f"  {p} | {h} | {u} | **** | {d} | {s}")

    input("\nConecta físicamente el PRIMER equipo y presiona ENTER para comenzar...")

    ok, skip = [], []
    for idx, (puerto, host, usr, pwd, dominio_ip, serie_csv) in enumerate(lista_completa_dispositivos, start=1):
        limpiar_pantalla_consola()
        print(f"[{idx}/{len(lista_completa_dispositivos)}] Conecta ahora el dispositivo:")
        print(f"  Puerto: {puerto}")
        print(f"  Host (Device): {host}")
        print(f"  Serie (CSV): {serie_csv}")
        input("ENTER cuando esté conectado...")

        exito = configurar_dispositivo_individual(
            puerto_com=puerto,
            nombre_host=host,                 # 👈 ahora viene directo de Device
            nombre_usuario=usr,
            clave_secreta=pwd,
            nombre_dominio=dominio_ip,
            serie_esperada=serie_csv          # seguimos validando que el SN coincida
        )
        if exito:
            ok.append(host)
        else:
            skip.append(host)

        print("\n=================================================")
        input("ENTER para continuar con el siguiente...")

    print("\nResumen:")
    print(f"✅ Configurados ({len(ok)}): {ok}")
    print(f"⏭️  Omitidos ({len(skip)}): {skip}")
    input("ENTER para volver al menú...")

# =============== Main loop ===============

if __name__ == "__main__":
    while True:
        presentar_menu_principal()
        opcion = input("Selecciona una opción: ").strip()
        if opcion == "1":
            menu_de_comandos_manuales()
        elif opcion == "2":
            flujo_de_configuracion_con_csv()
        elif opcion == "0":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")
            input("ENTER para continuar...")
