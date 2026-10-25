#!/bin/sh
# Compila o MicroPython v1.29.0 para ESP32 com o driver de rede do QEMU (open_eth).
# O firmware oficial (ESP32_GENERIC) NAO tem esse driver: network.LAN() trava o ESP32 emulado.
# Precisa de ~2,5 GB de disco (ESP-IDF 0,7 GB + ferramentas 1,4 GB + build 0,3 GB), ~3 min de build com 2 processos.
# Tudo vai pra laboratorio/.ferramentas (ou LAB_FERRAMENTAS); nada fica nesta pasta (que vai pro git).
set -e
REDE=$(cd "$(dirname "$0")" && pwd)
F=${LAB_FERRAMENTAS:-$(cd "$REDE/../../.." && pwd)/.ferramentas}
mkdir -p "$F/micropython"
PY312=$(uv python find 3.12)   # o Python 3.15 do sistema e novo demais para o ESP-IDF 5.5

# 1) ESP-IDF v5.5.2 (a versao recomendada pelo MicroPython 1.29) + so as ferramentas do ESP32
[ -d "$F/esp-idf" ] || git clone -q --depth 1 --branch v5.5.2 --recurse-submodules --shallow-submodules -j 2 \
    https://github.com/espressif/esp-idf.git "$F/esp-idf"
export IDF_TOOLS_PATH=$F/espressif
"$PY312" "$F/esp-idf/tools/idf_tools.py" install xtensa-esp-elf esp-rom-elfs cmake ninja
"$PY312" "$F/esp-idf/tools/idf_tools.py" install-python-env
. "$REDE/idf_env.sh"           # PATH sem o export.sh (que exige gdb/openocd) e ninja -j2

# 2) MicroPython + a placa ESP32_QEMU_ETH (sdkconfig com CONFIG_ETH_USE_OPENETH=y) + 1 correcao
MP=$F/micropython-src
[ -d "$MP" ] || git clone -q --depth 1 --branch v1.29.0 https://github.com/micropython/micropython.git "$MP"
cd "$MP"
git apply --check "$REDE/placa_qemu/openeth_esp32.patch" 2>/dev/null && git apply "$REDE/placa_qemu/openeth_esp32.patch"
make -s -C mpy-cross -j2
cd ports/esp32
make BOARD_DIR="$REDE/placa_qemu/ESP32_QEMU_ETH" BUILD=build-qemu-eth submodules
make BOARD_DIR="$REDE/placa_qemu/ESP32_QEMU_ETH" BUILD=build-qemu-eth
cp build-qemu-eth/firmware.bin "$F/micropython/ESP32_QEMU_ETH-$(date +%Y%m%d)-v1.29.0.bin"
echo "pronto: $F/micropython/ESP32_QEMU_ETH-$(date +%Y%m%d)-v1.29.0.bin (o QEMU precisa de -nic user,model=open_eth)"
