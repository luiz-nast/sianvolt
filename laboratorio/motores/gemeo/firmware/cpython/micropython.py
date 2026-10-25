# micropython.py: só pro gêmeo no CPython (o MicroPython de verdade já tem o dele)
def const(x):
    return x


def native(f):
    return f


viper = native


def schedule(f, arg):
    f(arg)


def alloc_emergency_exception_buf(n):
    pass


def mem_info(*a):
    print("mem_info: o gêmeo no CPython não mede a memória do ESP32")


def opt_level(*a):
    return 0


def heap_lock():
    pass


def heap_unlock():
    return 0
