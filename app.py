import socket
print("Hola soy Lucero")

hostaname=socket.gethostname()
print(f"hostname:{hostaname}")

IPAddress = socket.gethostbyname(hostaname)
print(f"IP Address: {IPAddress} ")

for i in range (10):
    print(i)


numero_a =int (input("dame le primer numero"))
numero_b = int (input("dame le segundo numero"))
print(f"la suma es:{numero_a+numero_b}")

print("resta",numero_a-numero_b)