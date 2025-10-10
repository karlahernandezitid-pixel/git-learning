import textfsm
import csv

# Archivos
TPL_FILE = "cisco_show_version.tpl"
TXT_FILE = "show_version.txt"
CSV_FILE = "show_version_parsed.csv"

with open(TPL_FILE) as tpl, open(TXT_FILE) as txt:
    fsm = textfsm.TextFSM(tpl)
    results = fsm.ParseText(txt.read())

# Imprime en pantalla
print(fsm.header)
for row in results:
    print(row)

# Guarda en CSV
with open(CSV_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(fsm.header)
    writer.writerows(results)

print(f"Archivo CSV generado: {CSV_FILE}")
