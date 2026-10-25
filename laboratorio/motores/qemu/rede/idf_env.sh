# carrega o ESP-IDF do laboratorio sem o export.sh (que exige gdb/openocd/ulp que nao instalamos).
# Quem chama define REDE (esta pasta) e F (laboratorio/.ferramentas); sem eles, adivinha pelo diretorio atual.
REDE=${REDE:-$(pwd)}
F=${F:-${LAB_FERRAMENTAS:-$(cd "$REDE/../../.." && pwd)/.ferramentas}}
export IDF_TOOLS_PATH=$F/espressif
export IDF_PATH=$F/esp-idf
export IDF_PYTHON_ENV_PATH=$IDF_TOOLS_PATH/python_env/idf5.5_py3.12_env
export ESP_ROM_ELF_DIR=$(echo $IDF_TOOLS_PATH/tools/esp-rom-elfs/*/)
for d in $IDF_TOOLS_PATH/tools/xtensa-esp-elf/*/xtensa-esp-elf/bin \
         $IDF_TOOLS_PATH/tools/riscv32-esp-elf/*/riscv32-esp-elf/bin \
         $IDF_TOOLS_PATH/tools/cmake/*/bin $IDF_TOOLS_PATH/tools/ninja/*; do
  [ -d "$d" ] && PATH=$d:$PATH
done
export PATH=$IDF_PYTHON_ENV_PATH/bin:$IDF_PATH/tools:$PATH
export LAB_FERRAMENTAS=$F
export PATH=$REDE/bin:$PATH   # ninja com -j2
