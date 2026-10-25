"""comum.py: o que é igual nos quatro chips (ESP32, C3, S3, C6) e a conferência de pino.

Cada chip (esp32.py, c3.py, s3.py, c6.py) faz 'from .comum import *' e acrescenta o que é dele.
Fontes:
  DS*  = datasheet de cada chip (texto em ~/.cache/sianvolt/lab/placas/ds_*.txt; a linha citada é desse texto)
  MPQ  = MicroPython quick reference ESP32, https://docs.micropython.org/en/latest/esp32/quickref.html
  MPC  = fonte do MicroPython v1.29.0, https://github.com/micropython/micropython/tree/v1.29.0/ports/esp32
"""
VDD = 3.3
# DC Characteristics dos 4 datasheets (ESP32 Tabela 5-3; C3, S3 e C6 Tabela 5-4): VIH mín 0,75 x VDD,
# VIL máx 0,25 x VDD, pull-up/pull-down de dentro 45 kΩ típicos, IOH 40 mA com VOH >= 2,64 V no drive máximo
VIH = 0.75 * VDD
VIL = 0.25 * VDD
R_PULL = 45e3
# MPQ: DRIVE_0 5 mA / 130 Ω, DRIVE_1 10 mA / 60 Ω, DRIVE_2 20 mA / 30 Ω (padrão), DRIVE_3 40 mA / 15 Ω.
# Bate com o IOH: (3,3 - 2,64) / 0,040 = 16,5 Ω. O pino de verdade satura; aqui é uma reta até a corrente segura.
DRIVE = {0: (130.0, 0.005), 1: (60.0, 0.010), 2: (30.0, 0.020), 3: (15.0, 0.040)}   # (ohms, corrente segura)
DRIVE_PADRAO = 2

# MPC machine_pin.c (gpio_mode_t do ESP-IDF): Pin.IN 1, OUT 3, OPEN_DRAIN 7; PULL_DOWN 1, PULL_UP 2
PIN_IN, PIN_OUT, PIN_OPEN_DRAIN = 1, 3, 7
PULL_DOWN, PULL_UP = 1, 2
IRQ_RISING, IRQ_FALLING = 1, 2
# MPC machine_pwm.c: PWM_FREQ 5000, duty padrão = metade
PWM_FREQ = 5000
PWM_DUTY_U16 = 32768
ADC_BITS = 12
# MPC machine_adc.c: sem atten, o ADC usa a máxima (ADC_ATTEN_MAX = 11 dB)
ATTEN_PADRAO = 3

# alimentação da placa (SUPOSIÇÃO, sem datasheet da placa): 3V3 sai de um regulador; VIN = 5 V do USB
R_3V3 = 0.05
V_VIN, R_VIN = 5.0, 0.5

# heap livre do MicroPython no começo do programa (gc.mem_free()) e quantos Timer(n) de hardware existem:
# cada chip preenche. HEAP_LIVRE vira o -X heapsize do MicroPython do PC (mais o que os stubs do gêmeo ocupam)
HEAP_LIVRE, HEAP_FONTE, TIMERS = None, "", 4

# o que cada chip preenche (vazio aqui)
SO_ENTRADA, FLASH, PSRAM, ADC2 = set(), set(), set(), set()
BOOT, SERIAL, DEVKIT = {}, {}, None
ADC2_WIFI = False


def conferir_pino(chip, gpio, saida=False, pull=None, com_placa=False):
    """levanta ValueError como o MicroPython de verdade; devolve os avisos [(texto, codigo)]"""
    if gpio not in chip.EXISTEM:
        raise ValueError("invalid pin")
    if saida and gpio in chip.SO_ENTRADA:
        raise ValueError("pin can only be input")
    nome, avisos = chip.CURTO, []
    if pull and gpio in chip.SO_ENTRADA:
        avisos.append(("GPIO%d não tem pull-up/pull-down por dentro (só entrada): o pull é ignorado" % gpio, "pull"))
    if gpio in chip.FLASH:
        avisos.append(("GPIO%d é da memória flash: mexer nele trava o %s de verdade" % (gpio, nome), "flash"))
    if gpio in chip.PSRAM:
        txt = getattr(chip, "PSRAM_AVISO", None) or "GPIO%d é da PSRAM (%s): só use se a placa não tiver PSRAM"
        avisos.append((txt % gpio if "%s" not in txt else txt % (gpio, chip.PSRAM_TXT), "psram"))
    if gpio in chip.BOOT and not com_placa:   # com o circuito, o gêmeo confere o nível de boot de verdade
        quer, _, porque = chip.BOOT[gpio]
        nivel = "tem que estar em %d (%s)" % (quer, porque) if quer is not None else "(%s)" % porque
        avisos.append(("GPIO%d é pino de boot: quando o %s liga ele %s; rode com --circuito pro gêmeo conferir"
                       % (gpio, nome, nivel), "boot"))
    if gpio in chip.SERIAL:
        avisos.append(("GPIO%d é %s: usar ele corta a conversa com o PC" % (gpio, chip.SERIAL[gpio]), "serial"))
    return avisos
