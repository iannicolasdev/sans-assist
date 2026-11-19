# Firmware SANS — ESP32

O ESP32 conecta-se ao Wi-Fi, recebe um evento JSON do Flask e sinaliza os LEDs.
Não classifica áudio e não faz requisições de volta ao backend.

## Configuração e gravação

Copie `include/secrets.example.h` para `include/secrets.h` e informe o Wi-Fi
de 2,4 GHz. `secrets.h` fica somente nesta máquina e não deve ser compartilhado.

```sh
pio run
pio run -t upload
pio device monitor -b 115200
```

O monitor serial mostra o IP atual da placa. Use esse endereço em
`./iniciar.sh IP_DO_ESP32`; o computador e o ESP32 precisam estar na mesma rede.

## LEDs

- GPIO 13 (amarelo): evento recebido.
- GPIO 26 (verde): evento JSON aceito pela placa.
- GPIO 14 (vermelho): requisição inválida.

O verde confirma apenas que o ESP32 recebeu o evento. O Flask já o salvou antes
de enviá-lo; isso não confirma que o usuário abriu ou viu o painel.

## Endpoint `POST /event`

O Flask envia um JSON com `event_id`, `device`, `event`, `description`,
`confidence` (0 a 1) e `timestamp`. O corpo deve ter no máximo 512 bytes.

Para testar somente a placa, substitua `IP_DO_ESP32` pelo endereço mostrado no
monitor serial:

```sh
curl -i -X POST http://IP_DO_ESP32/event \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "esp32-test-001",
    "device": "sans_phone_01",
    "event": "dog_barking",
    "description": "Cachorro latindo",
    "confidence": 0.94,
    "timestamp": "2026-11-15T22:00:00Z"
  }'
```

Esse teste direto acende os LEDs, mas não grava o evento no Flask. Para validar
o fluxo completo e o painel, use o simulador na interface ou siga
[`../docs/TESTE-MANUAL.md`](../docs/TESTE-MANUAL.md).
