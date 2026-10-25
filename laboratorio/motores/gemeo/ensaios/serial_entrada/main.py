# texto pela serial: input() espera, poll(200) espera no máximo 200 ms de placa, readline() espera
import sys, select, time
nome = input("nome? ")
print("oi, " + nome)
p = select.poll()
p.register(sys.stdin, select.POLLIN)
for i in range(3):
    if p.poll(200):
        print("chegou: " + sys.stdin.readline().strip())
    else:
        print("nada em " + str(time.ticks_ms()))
print("ultima: " + sys.stdin.readline().strip())
sys.stdin.readline()   # o roteiro não manda mais nada: fica esperando até o tempo acabar, como na placa
