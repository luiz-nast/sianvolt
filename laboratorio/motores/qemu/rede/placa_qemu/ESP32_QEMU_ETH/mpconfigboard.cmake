# ESP32 generico + driver de rede open_eth (so existe no QEMU da Espressif)
set(IDF_TARGET esp32)
include(boards/mpconfigboard_esp32_common.cmake)
list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.csi
    ${MICROPY_BOARD_DIR}/sdkconfig.qemu
)
