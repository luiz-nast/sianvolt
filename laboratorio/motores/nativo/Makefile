# Makefile do motor nativo: o sketch (o .ino que o nativo.py virou sketch.cpp) compilado pro PC com o g++,
# com o EpoxyDuino (MIT, https://github.com/bxparks/EpoxyDuino, v1.6.0) só pelo String/Print/Stream/IPAddress
# e o nosso núcleo (nucleo/: relógio virtual, pinos, Serial, main) no lugar do chip. Quem chama é o nativo.py:
#   make -s -j2 -f motores/nativo/Makefile EPOXY=.ferramentas/EpoxyDuino SABOR=esp32 CHIP=ESP32 \
#        FONTE=build/x/sketch.cpp PASTA=build/x/pisca SAIDA=build/x CACHE=build/.nativo/esp32
# SABOR esp32 (3,3 V, ADC 12 bits: as 4 ESP) ou uno (5 V, ADC 10 bits: o Nano). Só escreve em SAIDA e CACHE;
# cada .o é escrito num nome temporário e renomeado (duas rodadas ao mesmo tempo não estragam o CACHE).
AQUI  := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SABOR ?= esp32
CHIP  ?=
CORE  := $(EPOXY)/cores/epoxy

CORE_SRCS := $(filter-out $(CORE)/Arduino.cpp $(CORE)/main.cpp $(CORE)/StdioSerial.cpp,$(wildcard $(CORE)/*.cpp))
OBJS   := $(patsubst $(CORE)/%.cpp,$(CACHE)/epoxy_%.o,$(CORE_SRCS)) $(CACHE)/gemeo.o $(CACHE)/StdioSerial.o
EXTRAS := $(wildcard $(PASTA)/*.cpp $(PASTA)/src/*.cpp)   # .cpp que vêm junto do sketch
EXTRA_OBJS := $(patsubst %.cpp,$(SAIDA)/extra_%.o,$(notdir $(EXTRAS)))

DEFS_esp32 := -DPLACA_ESP32 $(if $(CHIP),-DCONFIG_IDF_TARGET_$(CHIP)=1) -I$(AQUI)nucleo/esp32
DEFS_uno   := -DARDUINO_AVR_NANO
CPPFLAGS := -DARDUINO=10819 -DEPOXY_DUINO -DUNIX_HOST_DUINO -DEPOXY_CORE_AVR $(DEFS_$(SABOR)) \
            -I$(AQUI)nucleo -I$(CORE) -iquote $(PASTA) -iquote $(PASTA)/src
CXXFLAGS := -std=gnu++17 -O1 -g -pipe
AVISOS   := -Wall -Wextra -Wno-unused-parameter
# compila num nome temporário e renomeia; o .d diz de que cabeçalhos o .o depende
COMPILA = $(CXX) $(CPPFLAGS) $(CXXFLAGS) $(1) -MMD -MP -MT $@ -MF $(@:.o=.d) -c $< -o $@.$$$$ && mv -f $@.$$$$ $@

$(SAIDA)/firmware: $(SAIDA)/sketch.o $(EXTRA_OBJS) $(OBJS)
	$(CXX) -o $@.$$$$ $^ && mv -f $@.$$$$ $@

$(SAIDA)/sketch.o: $(FONTE)
	@mkdir -p $(dir $@)
	$(call COMPILA,$(AVISOS))

$(SAIDA)/extra_%.o: $(PASTA)/%.cpp
	$(call COMPILA,$(AVISOS))

$(SAIDA)/extra_%.o: $(PASTA)/src/%.cpp
	$(call COMPILA,$(AVISOS))

$(CACHE)/epoxy_%.o: $(CORE)/%.cpp
	@mkdir -p $(dir $@)
	$(call COMPILA,-w)

$(CACHE)/%.o: $(AQUI)nucleo/%.cpp
	@mkdir -p $(dir $@)
	$(call COMPILA,-w)

-include $(wildcard $(SAIDA)/*.d $(CACHE)/*.d)
