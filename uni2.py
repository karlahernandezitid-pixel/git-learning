# find_ip_on_switches.py
# Requisitos: netmiko, textfsm, tabulate, ntc-templates (NET_TEXTFSM apuntando al dir 'templates')

import re
import ipaddress
from typing import Dict, List, Optional, Tuple

from netmiko import ConnectHandler
from tabulate import tabulate

# =============== AJUSTA ESTO A TU LAB ==================
USERNAME = "cisco"
PASSWORD = "cisco"

DEVICES = [
    {"name": "SW-CORE", "host": "192.168.1.1",  "device_type": "cisco_ios", "username": USERNAME, "password": PASSWORD},
    {"name": "SW1",     "host": "192.168.1.11", "device_type": "cisco_ios", "username": USERNAME, "password": PASSWORD},
    {"name": "SW2",     "host": "192.168.1.12", "device_type": "cisco_ios", "username": USERNAME, "password": PASSWORD},
]
CORE_NAME = "SW-CORE"   # desde aquí haremos ping y ARP
SUBNET = ipaddress.ip_network("192.168.1.0/24")
VLAN_INTEREST = "1"      # por simplicidad

PING_COUNT = 2
PING_TIMEOUT_MS = 500

# =======================================================

def connect(device: Dict) -> ConnectHandler:
    return ConnectHandler(**device)

def normalize_mac(mac: str) -> str:
    mac = mac.strip().lower()
    mac = mac.replace(".", "").replace("-", "").replace(":", "")
    # formatear a xxxx.xxxx.xxxx (Cisco-style)
    if len(mac) == 12:
        return f"{mac[0:4]}.{mac[4:8]}.{mac[8:12]}"
    return mac

def get_core_conn() -> Tuple[Dict, ConnectHandler]:
    core = next(d for d in DEVICES if d["name"] == CORE_NAME)
    return core, connect(core)

def ping_from_core(core_conn: ConnectHandler, ip: str) -> None:
    # Esto ayuda a popular ARP
    cmd = f"ping {ip} repeat {PING_COUNT} timeout {PING_TIMEOUT_MS}"
    core_conn.send_command(cmd)  # no importa el resultado exacto; solo para "tocarlo"

def get_mac_from_ip(core_conn: ConnectHandler, ip: str) -> Optional[str]:
    # Intenta TextFSM con 'show ip arp <ip>' (ntc-templates: cisco_ios_show_ip_arp)
    out = core_conn.send_command(f"show ip arp {ip}", use_textfsm=True)
    # Algunos IOS usan 'show arp'
    if isinstance(out, list) and len(out) == 0:
        out = core_conn.send_command(f"show arp {ip}", use_textfsm=True)

    if isinstance(out, list) and len(out) > 0:
        # ntc-templates keys usuales: 'address','protocol','age','mac','interface'
        entry = out[0]
        mac = entry.get("mac") or entry.get("hardware_addr")
        return normalize_mac(mac) if mac else None

    # Fallback regex (si no hay templates)
    raw = core_conn.send_command(f"show ip arp {ip}")
    m = re.search(r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|[0-9a-fA-F]{2}([:\-.]?)){5}[0-9a-fA-F]{2}", raw)
    return normalize_mac(m.group(0)) if m else None

def get_lldp_uplinks(conn: ConnectHandler) -> set:
    """Devuelve un set de interfaces locales que tienen vecinos (posibles troncales)."""
    uplinks = set()
    try:
        # cisco_ios_show_lldp_neighbors or neighbors_detail templates
        out = conn.send_command("show lldp neighbors detail", use_textfsm=True)
        if isinstance(out, list):
            for n in out:
                local_intf = n.get("local_interface") or n.get("local_intf")
                if local_intf:
                    uplinks.add(local_intf)
    except Exception:
        pass
    return uplinks

def find_mac_on_switch(conn: ConnectHandler, mac: str) -> List[Dict]:
    """Busca la MAC en show mac address-table; regresa lista de coincidencias."""
    results = []
    try:
        # 'cisco_ios_show_mac_address_table' template regresa campos comunes:
        # destination_address, destination_port, type, vlan
        table = conn.send_command("show mac address-table", use_textfsm=True)
        if isinstance(table, list):
            for row in table:
                if normalize_mac(row.get("destination_address","")) == mac:
                    results.append({
                        "vlan": str(row.get("vlan", "")),
                        "port": row.get("destination_port", ""),
                        "type": row.get("type", "")
                    })
            return results
    except Exception:
        pass

    # Fallback: filtrar manual
    raw = conn.send_command("show mac address-table")
    for line in raw.splitlines():
        if mac in line.lower():
            # Ejemplo de línea: " 1    dddd.dddd.dddd   DYNAMIC Gi1/0/15"
            parts = line.split()
            # heurística
            vlan = parts[0] if parts else ""
            typ  = parts[-2] if len(parts) >= 2 else ""
            port = parts[-1] if parts else ""
            results.append({"vlan": vlan, "port": port, "type": typ})
    return results

def resolve_location(ip: str) -> Optional[Dict]:
    """Devuelve dict con switch, puerto, vlan, mac, ip; o None si no se encontró."""
    core_dev, core_conn = get_core_conn()
    try:
        # 1) ping para poblar ARP
        ping_from_core(core_conn, ip)
        # 2) sacar MAC desde ARP del CORE
        mac = get_mac_from_ip(core_conn, ip)
        if not mac:
            return None

        # 3) buscar MAC en todos los switches
        best_match = None
        for dev in DEVICES:
            conn = None
            try:
                conn = connect(dev)
                lldp_uplinks = get_lldp_uplinks(conn)  # puertos que "parecen" troncales
                matches = find_mac_on_switch(conn, mac)
                # prioriza:
                #  - VLAN 1 (si coincide)
                #  - PUERTO que NO esté en uplinks LLDP (probable puerto de usuario)
                #  - TYPE DYNAMIC
                #  - Si no, toma cualquiera
                ranked = sorted(
                    matches,
                    key=lambda r: (
                        0 if str(r.get("vlan","")) == VLAN_INTEREST else 1,
                        0 if r.get("port","") not in lldp_uplinks else 1,
                        0 if str(r.get("type","")).upper() == "DYNAMIC" else 1
                    )
                )
                if ranked:
                    cand = ranked[0]
                    best_match = {
                        "switch": dev["name"],
                        "ip": ip,
                        "mac": mac,
                        "port": cand.get("port",""),
                        "vlan": cand.get("vlan",""),
                        "type": cand.get("type","")
                    }
                    # Si ya encontramos un puerto que no es uplink y es VLAN 1 dinámico, paramos.
                    if (best_match["vlan"] == VLAN_INTEREST
                        and best_match["port"] not in lldp_uplinks
                        and str(best_match["type"]).upper() == "DYNAMIC"):
                        return best_match
            finally:
                if conn:
                    conn.disconnect()

        return best_match
    finally:
        core_conn.disconnect()

def main():
    print("=== Localizador de IP -> (Switch, Puerto, MAC) con Netmiko+TextFSM ===")
    print("Escribe 'salir' para terminar.\n")

    while True:
        ip = input("CONSOLA: { ¿Qué IP quieres encontrar? } ").strip()
        if ip.lower() in ("salir", "exit", "quit"):
            break

        # Validación básica de IP y subred
        try:
            ip_addr = ipaddress.ip_address(ip)
            if ip_addr not in SUBNET:
                print(f"[!] La IP {ip} no está en la subred {SUBNET}. (Continuo de todos modos)")
        except ValueError:
            print("[!] IP no válida, intenta de nuevo.\n")
            continue

        info = resolve_location(ip)
        if not info:
            print(f"[x] No encontré información para {ip}. Puede que no tenga ARP/MAC aún.")
            print("    Tip: asegúrate que la laptop esté conectada y que haya tráfico (o prueba de nuevo).\n")
            continue

        table = [
            ["Switch", info["switch"]],
            ["IP", info["ip"]],
            ["MAC", info["mac"]],
            ["Puerto", info["port"]],
            ["VLAN", info["vlan"]],
            ["Tipo (MAC table)", info["type"]],
        ]
        print("\n" + tabulate(table, headers=["Campo", "Valor"], tablefmt="fancy_grid") + "\n")

if __name__ == "__main__":
    main()
