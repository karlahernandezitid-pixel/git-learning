# TPL para 'show ip interface brief' (Cisco IOS/IOS-XE)
Value Required INTERFACE (\S+)
Value IPADDR (\S+)
Value OK (\S+)
Value METHOD (\S+)
Value STATUS (administratively down|up|down|deleted|reset|testing|unknown)
Value PROTOCOL (up|down)

Start
  ^\s*Interface\s+IP[\- ]Address\s+OK\?\s+Method\s+Status\s+Protocol\s*$ -> Continue
  ^${INTERFACE}\s+${IPADDR}\s+${OK}\s+${METHOD}\s+${STATUS}\s+${PROTOCOL}\s*$ -> Record
  ^.* -> Continue
