import time
n = 0
while True:
    try:
        time.sleep(1)
        n += 1
    except:          # engole tudo, até o fim da simulação
        pass
