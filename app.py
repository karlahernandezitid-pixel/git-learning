import socket
print("Hola soy Lucero")

hostaname=socket.gethostname()
print(f"hostname:{hostaname}")

IPAddress = socket.gethostbyname(hostaname)
print(f"IP Address: {IPAddress} ")




