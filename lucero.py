# ip_port_finder.py — misma lógica; parsers y variantes reforzadas

from netmiko import ConnectHandler
import re, sys

# ==== MODO DISCRETO: oculta prints de conexiones por switch ====
import builtins as _bi
def enable_discreet_mode():
    """
    Oculta mensajes que delatan conexión/consulta a cada switch,
    dejando visibles encabezados, resultados y errores finales.
    NO cambia la lógica del script: solo filtra ciertos prints.
    """
    _orig_print = _bi.print
    HIDE_IF_CONTAINS = (
        "↪ Consultando [",        # ETAPA 1: probando cada switch
        "↪ Buscando MAC",         # ETAPA 2: probando cada switch
        "... Sin registros para", # salida intermedia por switch
        "... MAC vista en",       # hallazgo por switch
        "ERROR conectando a",     # errores por equipo intermedio
    )
    def _filtered_print(*args, **kwargs):
        try:
            msg = " ".join(str(a) for a in args)
        except Exception:
            msg = ""
        if any(token in msg for token in HIDE_IF_CONTAINS):
            return  # suprime mensaje discreto
        return _orig_print(*args, **kwargs)
    _bi.print = _filtered_print
# ===============================================================

EQUIPOS_RED = [
    {"device_type": "cisco_ios", "ip": "192.168.1.11", "username": "cisco", "password": "cisco99", "host_name": "SW1"},
    {"device_type": "cisco_ios", "ip": "192.168.1.1",  "username": "cisco", "password": "cisco99", "host_name": "SW-CORE"},
    {"device_type": "cisco_ios", "ip": "192.168.1.12", "username": "cisco", "password": "cisco99", "host_name": "SW2"},
]
VLAN_BUSQUEDA = "1"

MAC_PATTERNS = [
    r"[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}",
    r"[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}",
    r"[0-9a-fA-F]{12}",
]

def normalizar_mac(s): 
    return re.sub(r"[^0-9a-fA-F]", "", s or "").lower()

def buscar_mac_en_texto(txt):
    for p in MAC_PATTERNS:
        m = re.search(p, txt or "")
        if m: return m.group(0)
    return None

def line_contains_ip(line, ip):
    # Coincidencia con bordes para no confundir 1.1.1.1 dentro de 11.1.1.10
    return re.search(rf"(?<!\d){re.escape(ip)}(?!\d)", line or "") is not None

def conectar(dev):
    params = {
        "device_type": dev["device_type"],
        "host": dev["ip"],
        "username": dev["username"],
        "password": dev["password"],
        "fast_cli": True,
        "global_delay_factor": 1.0,
    }
    if dev.get("secret"): params["secret"] = dev["secret"]
    c = ConnectHandler(**params)
    try: c.send_command_timing("terminal length 0", strip_command=False)
    except: pass
    try:
        if dev.get("secret"): c.enable()
    except: pass
    return c

def extraer_vlan_de_interfaz(ifn):
    m = re.search(r"[Vv]lan(\d+)", ifn or "")
    return m.group(1) if m else None

def extraer_vlan_de_texto(linea):
    m = re.search(r"[Vv][Ll][Aa][Nn]\s*:?[\s#]*([0-9]+)", linea or "")
    return m.group(1) if m else None

# ---- normalización de nombres de interfaz y filtro de físicos /48 ---
SHORT2LONG = {
    "fa": "FastEthernet", "gi": "GigabitEthernet", "te": "TenGigabitEthernet",
    "po": "Port-channel", "vl": "Vlan", "lo": "Loopback", "se": "Serial"
}
def if_long(n):
    n = (n or "").strip()
    for pfx in ("FastEthernet","GigabitEthernet","TenGigabitEthernet","Port-channel","Vlan","Loopback","Serial"):
        if n.lower().startswith(pfx.lower()): return n
    m = re.match(r"^([A-Za-z]+)(.+)$", n)
    if not m: return n
    pre, rest = m.group(1).lower(), m.group(2)
    return f"{SHORT2LONG.get(pre[:2], m.group(1))}{rest}"

def es_puerto_fisico_48(p):
    p = if_long(p)
    if p.upper() in ("CPU","ROUTER"): return False
    if p.lower().startswith(("vlan","port-channel")): return False
    m = re.search(r"(FastEthernet|GigabitEthernet|TenGigabitEthernet)\d*/?\d*/?(\d+)$", p, re.I)
    return bool(m and int(m.group(2)) <= 48)

# ----------------- ETAPA 1: IP -> MAC -----------------
def descubrir_mac_por_ip(sesion, ip_addr):
    # (A) IP DEL MISMO SWITCH (SVI/Loopback/mgmt)
    try:
        out = sesion.send_command(f"show ip interface brief | include {ip_addr}", use_textfsm=False, read_timeout=20)
        if line_contains_ip(out, ip_addr):
            # línea tipo: Vlan10   192.168.1.1   YES manual up up
            m_if = re.search(rf"^(\S+)\s+{re.escape(ip_addr)}\b", out, re.M)
            if m_if:
                ifz = m_if.group(1)
                det = sesion.send_command(f"show interface {ifz} | include address is", use_textfsm=False, read_timeout=20)
                # "Hardware is ..., address is 001b.2b3c.4d5e (bia ...)"
                m_mac = re.search(r"address is\s+([0-9a-fA-F\.\:]+)", det or "", re.I)
                mac = m_mac.group(1) if m_mac else None
                vlan_id = extraer_vlan_de_interfaz(ifz) or extraer_vlan_de_texto(out)
                if mac:
                    return {"ip": ip_addr, "hw_addr": mac, "fuente": "local-if", "vlan_id": vlan_id, "ifaz": ifz}
    except: pass

    # (B) DHCP Snooping
    for cmd in (f"show ip dhcp snooping binding | include {ip_addr}", "show ip dhcp snooping binding"):
        try:
            out = sesion.send_command(cmd, use_textfsm=False, read_timeout=20)
            if not out: continue
            # busca línea exacta que contenga esa IP
            linea = next((l for l in out.splitlines() if line_contains_ip(l, ip_addr)), "")
            if not linea: 
                continue
            mac = buscar_mac_en_texto(linea)
            vlan_id, ifz = None, None
            # patron robusto: <IP> <MAC> <Lease/Type> <VLAN> <Interface>
            m = re.search(r"\s(\d+)\s+([A-Za-z]+\d+(?:/\d+)*\S*)", linea)
            if m: vlan_id, ifz = m.group(1), m.group(2)
            if not vlan_id: vlan_id = extraer_vlan_de_texto(linea)
            if not vlan_id and ifz: vlan_id = extraer_vlan_de_interfaz(ifz)
            if mac:
                return {"ip": ip_addr, "hw_addr": mac, "fuente": "dhcp", "vlan_id": vlan_id, "ifaz": ifz}
        except: pass

    # (C) ARP puntual (variante clásica y formato “Protocol Address …”)
    try:
        out = sesion.send_command(f"show ip arp {ip_addr}", use_textfsm=False, read_timeout=20)
        if out and line_contains_ip(out, ip_addr):
            linea = next((l for l in out.splitlines() if line_contains_ip(l, ip_addr)), "")
            mac = buscar_mac_en_texto(linea)
            # termina con interfaz
            m_if = re.search(r"\s([A-Za-z0-9/\.]+)\s*$", linea)
            ifz = m_if.group(1) if m_if else None
            vlan_id = extraer_vlan_de_interfaz(ifz or "") or extraer_vlan_de_texto(linea)
            if mac:
                return {"ip": ip_addr, "hw_addr": mac, "fuente": "arp", "vlan_id": vlan_id, "ifaz": ifz}
    except: pass

    # (D) ARP general (incluye VRFs)
    for cmd in ("show ip arp", "show arp", "show ip arp vrf all"):
        try:
            out = sesion.send_command(cmd, use_textfsm=False, read_timeout=25)
            if not out: continue
            linea = next((l for l in out.splitlines() if line_contains_ip(l, ip_addr)), "")
            if not linea: 
                continue
            mac = buscar_mac_en_texto(linea)
            m_if = re.search(r"\s([A-Za-z0-9/\.]+)\s*$", linea)
            ifz = m_if.group(1) if m_if else None
            vlan_id = extraer_vlan_de_interfaz(ifz or "") or extraer_vlan_de_texto(linea)
            if mac:
                return {"ip": ip_addr, "hw_addr": mac, "fuente": "arp-scan", "vlan_id": vlan_id, "ifaz": ifz}
        except: pass

    # (E) IP Device Tracking (variantes)
    for cmd in (f"show ip device tracking all | include {ip_addr}",
                "show ip device tracking all",
                f"show device tracking database | include {ip_addr}",
                "show device tracking database"):
        try:
            out = sesion.send_command(cmd, use_textfsm=False, read_timeout=25)
            if not out: continue
            linea = next((l for l in out.splitlines() if line_contains_ip(l, ip_addr)), "")
            if not linea: 
                continue
            mac = buscar_mac_en_texto(linea)
            m_if = re.search(r"\s([A-Za-z]+[0-9/\.]+)\s", linea)
            ifz = m_if.group(1) if m_if else None
            vlan_id = extraer_vlan_de_texto(out) or extraer_vlan_de_interfaz(ifz or "")
            if mac:
                return {"ip": ip_addr, "hw_addr": mac, "fuente": "device-tracking", "vlan_id": vlan_id, "ifaz": ifz}
        except: pass

    return None

# ----------- Caracterización del puerto (uplink vs access) -------------
def caracterizar_puerto(sesion, ifname):
    data = {"is_trunk": False, "is_access": False, "access_vlan": None,
            "native_vlan": None, "mac_count": None, "has_neighbor": False}
    try:
        sw = sesion.send_command(f"show interfaces {ifname} switchport", use_textfsm=False, read_timeout=20)
        if re.search(r"(Operational|Administrative)\s+Mode:\s*trunk", sw or "", re.I): data["is_trunk"] = True
        if re.search(r"Access Mode VLAN:", sw or "", re.I) and not data["is_trunk"]: data["is_access"] = True
        m = re.search(r"Access Mode VLAN:\s*(\d+)", sw or "", re.I)
        if m: data["access_vlan"] = m.group(1)
        m = re.search(r"Trunking Native Mode VLAN:\s*(\d+)", sw or "", re.I)
        if m: data["native_vlan"] = m.group(1)
    except: pass
    try:
        cdp = sesion.send_command(f"show cdp neighbors interface {ifname} detail", use_textfsm=False, read_timeout=15)
        if re.search(r"Device ID|System Name", cdp or "", re.I): data["has_neighbor"] = True
    except: pass
    try:
        lldp = sesion.send_command(f"show lldp neighbors interface {ifname} detail", use_textfsm=False, read_timeout=15)
        if re.search(r"System Name|Chassis id", lldp or "", re.I): data["has_neighbor"] = True
    except: pass
    try:
        out = sesion.send_command(f"show mac address-table interface {ifname}", use_textfsm=False, read_timeout=15)
        cnt = len(re.findall(r"(?i)\bDYNAMIC\b", out or "")) or len(re.findall(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}", out or "", re.I))
        data["mac_count"] = cnt
    except: pass
    return data

# ----------------- ETAPA 2: MAC -> PUERTO -----------------
def buscar_puerto_por_mac(sesion, mac_addr, vlan_hint=None):
    mac_norm = normalizar_mac(mac_addr)
    variants = {
        "dot": f"{mac_norm[0:4]}.{mac_norm[4:8]}.{mac_norm[8:12]}",
        "colon": ":".join([mac_norm[i:i+2] for i in range(0,12,2)]),
        "plain": mac_norm
    }
    comandos = []
    if vlan_hint:
        comandos += [f"show mac address-table vlan {vlan_hint} address {variants['dot']}"]
    comandos += [
        f"show mac address-table address {variants['dot']}",
        f"show mac address-table address {variants['colon']}",
        f"show mac address-table | include {variants['dot']}",
        f"show mac address-table | include {variants['colon']}",
        f"show mac address-table | include {variants['plain']}",
        "show mac address-table"
    ]

    cand_port = None
    for cmd in comandos:
        try:
            out = sesion.send_command(cmd, use_textfsm=False, read_timeout=20)
            if not (out or "").strip(): 
                continue
            for ln in (out or "").splitlines():
                if not any(v in ln for v in variants.values()): 
                    continue
                if re.search(r"\b(CPU|ROUTER)\b", ln, re.I): 
                    continue
                # VLAN
                m_vlan = re.search(r"\s(\d+)\s", ln)
                vlan_id = m_vlan.group(1) if m_vlan else vlan_hint
                # Puerto (si hay lista “Gi1/0/48,Po1” nos quedamos con el físico)
                m_ports = re.search(r"([A-Za-z]+\d+(?:/\d+)*\S*)\s*$", ln)
                if not m_ports: 
                    continue
                raw = m_ports.group(1)
                first = raw.split(",")[0]
                port = if_long(first)
                if not es_puerto_fisico_48(port):
                    continue
                cand_port = port
                car = caracterizar_puerto(sesion, port)
                return {
                    "puerto": port, "vlan_id": vlan_id, "tipo": "DYNAMIC",
                    "is_trunk": car["is_trunk"], "is_access": car["is_access"],
                    "access_vlan": car["access_vlan"], "native_vlan": car["native_vlan"],
                    "mac_count": car["mac_count"], "has_neighbor": car["has_neighbor"],
                }
        except: 
            continue

    # Si no hubo retorno pero vimos algún puerto candidato, al menos devuélvelo
    if cand_port:
        return {"puerto": cand_port, "vlan_id": vlan_hint, "tipo": "UNKNOWN",
                "is_trunk": False, "is_access": False, "access_vlan": None,
                "native_vlan": None, "mac_count": None, "has_neighbor": False}
    return None

# ----------------- ORQUESTADOR (misma lógica) -----------------
def iniciar_localizacion_ip(ip_objetivo):
    print("\n" + "="*50)
    print("  🔎 INICIANDO RASTREO DE DISPOSITIVO 🔎")
    print(f"  IP Objetivo: {ip_objetivo}")
    print("="*50 + "\n")

    # ETAPA 1
    print("--- [ETAPA 1: Resolución IP -> MAC] ---")
    datos_mac, equipo_origen = None, None
    for eq in EQUIPOS_RED:
        print(f"  ↪ Consultando [{eq['host_name']}]...")
        try:
            s = conectar(eq)
            info = descubrir_mac_por_ip(s, ip_objetivo)
            s.disconnect()
            if info:
                datos_mac, equipo_origen = info, eq
                print(f"  💡 ¡MAC resuelta! En [{eq['host_name']}]")
                print(f"     HW Address: {info['hw_addr']} (Fuente: {info['fuente']})")
                print(f"     Info: IF:{info.get('ifaz','?')} VLAN:{info.get('vlan_id','?')}\n")
                break
            else:
                print(f"     ... Sin registros para {ip_objetivo}.")
        except Exception as e:
            print(f"  ❌ ERROR conectando a {eq['host_name']} ({eq['ip']}): {e}")

    if not datos_mac:
        print("\n" + "-"*50)
        print("  ⛔ RASTREO FALLIDO (ETAPA 1)")
        print(f"  No se pudo determinar la MAC para {ip_objetivo}.")
        print("-"*50 + "\n")
        return

    # ETAPA 2
    print("\n--- [ETAPA 2: Localización MAC -> Puerto] ---")
    mac = datos_mac["hw_addr"]
    mejor, equipo_final = None, None
    vlan_hint = datos_mac.get("vlan_id")

    for eq in EQUIPOS_RED:
        print(f"  ↪ Buscando MAC {mac} en [{eq['host_name']}]...")
        try:
            s = conectar(eq)
            d = buscar_puerto_por_mac(s, mac, vlan_hint=vlan_hint)
            s.disconnect()
            if d:
                print(f"     ... MAC vista en {d['puerto']}  (VLAN:{d.get('vlan_id')}  tipo:{d.get('tipo')})")
                # mismo scoring que ya tenías
                score = 0
                score += 60 if (d.get("is_access") and not d.get("is_trunk")) else -60
                if d.get("has_neighbor"): score -= 30
                mc = d.get("mac_count") or 0
                if mc >= 8: score -= 25
                elif mc >= 3: score -= 12
                else: score += 8
                if VLAN_BUSQUEDA and (d.get("vlan_id") == VLAN_BUSQUEDA or d.get("access_vlan") == VLAN_BUSQUEDA):
                    score += 10
                if re.search(r"Po\d+|Port-Channel|^Te|^Fo", d["puerto"], re.I): score -= 40

                d["score"] = score
                if (mejor is None) or (score > mejor["score"]):
                    mejor, equipo_final = d, eq
        except Exception as e:
            print(f"  ❌ ERROR conectando a {eq['host_name']} ({eq['ip']}): {e}")

    if mejor and equipo_final:
        print("\n" + "*"*50)
        print("  ✅ RASTREO COMPLETADO CON ÉXITO ✅")
        print("*"*50)
        print(f"    💻 Switch:        {equipo_final['host_name']}")
        print(f"    🔌 Puerto:         {mejor['puerto']}")
        print(f"    🌐 IP Consultada:  {ip_objetivo}")
        print(f"    🏷 MAC Address:    {mac}")
        print(f"    🛂 VLAN Detectada: {mejor.get('vlan_id') or mejor.get('access_vlan') or datos_mac.get('vlan_id','?')}")
        print(f"    ℹ  Puerto:        {'ACCESS' if mejor.get('is_access') else 'TRUNK'}"
              f" | Vecino:{'sí' if mejor.get('has_neighbor') else 'no'}"
              f" | MACs:{mejor.get('mac_count')}")
        print("*"*50 + "\n")
    else:
        print("\n" + "-"*50)
        print("  ⚠ RASTREO INCOMPLETO (ETAPA 2)")
        print(f"  MAC resuelta pero no localizada en CAM Tables.")
        print(f"  IP:{ip_objetivo} | MAC:{mac} | Origen:{equipo_origen['host_name']}")
        print("-"*50 + "\n")

if __name__ == "__main__":
    enable_discreet_mode()  
    print("--- Herramienta de Localización de IP en Red Cisco ---")
    while True:
        ip_usuario = input("\n>>> Introduce la IP a localizar (o 'salir'): ").strip()
        if ip_usuario.lower() == "salir":
            print("Cerrando aplicación. ¡Bye!")
            break
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip_usuario):
            print("[!] Formato IP inválido. Ej: 192.168.1.30")
            continue
        try:
            iniciar_localizacion_ip(ip_usuario)
        except KeyboardInterrupt:
            print("\n🛑 Cancelado por el usuario.")
            sys.exit(0)
        except Exception as e:
            print(f"\n[!!] Error inesperado: {e}")
