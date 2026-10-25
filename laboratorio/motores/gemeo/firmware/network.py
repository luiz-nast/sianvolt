# network.py do gêmeo: Wi-Fi de faz de conta. Conecta (ou falha, se o roteiro mandar) em 1,5 s de placa.
# Não manda nada pela rede: socket, urequests e afins não existem no gêmeo.
from _ponte import rpc

STA_IF = 0
AP_IF = 1
STAT_IDLE = 1000
STAT_CONNECTING = 1001
STAT_GOT_IP = 1010


class WLAN:
    def __init__(self, interface=STA_IF):
        self._if = interface

    def active(self, v=None):
        return rpc("wlan_ativa", None if v is None else bool(v))

    def connect(self, ssid=None, key=None, **kw):
        rpc("wlan_conecta", ssid)

    def disconnect(self):
        pass

    def isconnected(self):
        return rpc("wlan_conectado")

    def status(self, *a):
        return STAT_GOT_IP if self.isconnected() else STAT_CONNECTING

    def ifconfig(self, *a):
        return ("192.168.0.50", "255.255.255.0", "192.168.0.1", "8.8.8.8") if self.isconnected() else ("0.0.0.0",) * 4

    def config(self, *a, **kw):
        if a and a[0] == "mac":
            return b"\x24\x0a\xc4\x00\x00\x01"
        return None

    def scan(self):
        return []
