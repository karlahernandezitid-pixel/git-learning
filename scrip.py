import serial
import time
import pandas as pd
import os
import re

def limpiar_pantalla_consola():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

def enviar_comando_al_equipo(puerto_serial, comando_para_enviar, retraso=1):
    puerto_serial.write((comando_para_enviar + "\r\n").encode())
    time.sleep(retraso)
    respuesta_del_equipo = puerto_serial.read(puerto_serial.in_waiting).decode(errors="ignore")
    return respuesta_del_equipo

def obtener_numero_de_serie(conexion_serial):
    enviar_comando_al_equipo(conexion_serial, "terminal length 0")
    salida_inventario = enviar_comando_al_equipo(conexion_serial, "show inventory", retraso=2)
    coincidencia_serie = re.search(r"SN:\s*([A-Z0-9]+)", salida_inventario)
    if coincidencia_serie:
        return coincidencia_serie.group(1)
    return None

def configurar_dispositivo_individual(puerto_com, nombre_host, nombre_usuario, clave_secreta, nombre_dominio):
    try:
        conexion_activa = serial.Serial(puerto_com, baudrate=9600, timeout=1)
        time.sleep(2)
        print(f"\n🔗 Intentando conexión en {puerto_com} ({nombre_host})")

        serial_obtenido = obtener_numero_de_serie(conexion_activa)
        if not serial_obtenido:
            print("Fallo al obtener el número de serie")
            conexion_activa.close()
            return False

        if nombre_host[1:] != serial_obtenido:
            print(f"Número de serie: ({serial_obtenido}) no coincide con el del archivo ({nombre_host[1:]})")
            conexion_activa.close()
            return False

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

        print(f"Se ha aplicado la configuración en {nombre_host}.")
        conexion_activa.close()
        return True

    except Exception as excepcion_ocurrida:
        print(f"No se pudo configurar el dispositivo {nombre_host}: {excepcion_ocurrida}")
        return False

def presentar_menu_principal():
    limpiar_pantalla_consola()
    print("=== MENÚ ===")
    print("1. Comandos manuales")
    print("2. Configuraciones")
    print("0. Salir")

def menu_de_comandos_manuales():
    puerto_de_conexion = input("¿En que puerto estas conectado? -> ")
    try:
        sesion_serial = serial.Serial(puerto_de_conexion, baudrate=9600, timeout=1)
        time.sleep(2)
        print(f"\nConectado en {puerto_de_conexion}")
        while True:
            comando_ingresado = input("Ingresa el comando (o 'exit' para salir): ")
            if comando_ingresado.lower() == "exit":
                break
            salida_del_comando = enviar_comando_al_equipo(sesion_serial, comando_ingresado, retraso=2)
            print(f"\nSalida:\n{salida_del_comando}")
        sesion_serial.close()
    except Exception as error_general:
        print(f"No se pudo conectar: {error_general}")
    input("ENTER para volver...")

def flujo_de_configuracion_con_csv():
    limpiar_pantalla_consola()
    try:
        ruta_archivo = r"C:\Users\lucer\OneDrive\Documentos\Gip\DATA.csv"
        dataframe_dispositivos = pd.read_csv(ruta_archivo)

    except FileNotFoundError:
        print("\nNo se encontró el archivo en la ruta especificada.")
        print(f"Asegúrate de que el archivo exista en: {ruta_archivo}")
        input("Presione ENTER para volver al menú...")
        return
        
    print("\nArchivo:")
    print(dataframe_dispositivos)

    NombresDeHostGenerados = [str(d).strip()[0] + str(s).strip() for d, s in zip(dataframe_dispositivos['Device'], dataframe_dispositivos['Serie'])]
    lista_completa_dispositivos = [(p, h, u, pas, dom) for p, u, pas, dom, h in zip(dataframe_dispositivos['Port'], dataframe_dispositivos['User'], dataframe_dispositivos['Password'], dataframe_dispositivos['Ip-domain'], NombresDeHostGenerados)]

    print("\nDispositivos y configuraciones:")
    for elemento in lista_completa_dispositivos:
        print(elemento)
    input("Presione ENTER para continuar...")

    dispositivos_configurados_ok = []
    dispositivos_omitidos = []

    for indice, (puerto, host, usr, pwd, dominio_ip) in enumerate(lista_completa_dispositivos, start=1):
        limpiar_pantalla_consola()
        print(f"\nConecte ahora el dispositivo {indice}: {host} en el puerto {puerto}")
        input("Presione ENTER cuando el dispositivo esté conectado...")
        fue_exitoso = configurar_dispositivo_individual(puerto, host, usr, pwd, dominio_ip)
        if fue_exitoso:
            dispositivos_configurados_ok.append(host)
        else:
            dispositivos_omitidos.append(host)
        print("=================================================")
        input("Presione ENTER para continuar...")

if __name__ == "__main__":
    while True:
        presentar_menu_principal()
        opcion_elegida = input("Selecciona una opción: ")
        if opcion_elegida == "1":
            menu_de_comandos_manuales()
        elif opcion_elegida == "2":
            flujo_de_configuracion_con_csv()
        elif opcion_elegida == "0":
            print("Saliendo del programa...")
            break
        else:
            print("Opción inválida.")
            input("Presione ENTER para continuar...")