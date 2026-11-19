# SANS — Arquitetura atual

## Objetivo

Transformar sons importantes em eventos visuais para apoiar pessoas surdas ou
com deficiência auditiva. O ESP32 e os LEDs existentes são mantidos; o
microfone INMP441 não é necessário nesta versão.

## Fluxo único

1. O dispositivo sensor captura o áudio e executa YAMNet no navegador.
2. O dispositivo envia ao Flask somente `event_id`, `event`, `confidence` e
   `timestamp` em JSON. Áudio bruto não é enviado.
3. O Flask valida e grava o evento no SQLite.
4. O Flask envia o mesmo JSON ao ESP32 pela rede Wi-Fi local.
5. O ESP32 acende amarelo e depois verde ao aceitar a notificação.
6. O celular do usuário consulta o painel Flask, que atualiza a cada 5 segundos.

O Flask centraliza a comunicação. Não há chamada direta do navegador ao ESP32,
nem encaminhamento ESP32 → Flask de volta. O endpoint do ESP32 é `POST /event`;
os eventos do celular chegam a `POST /api/sensor-event`.

## Responsabilidades e limites

- **Dispositivo sensor:** permissão do microfone, classificação local, limiar de
  confiança e intervalo entre eventos repetidos. Precisa manter a página aberta
  e a tela ligada; captura em segundo plano não é suportada.
- **Flask:** validação, persistência SQLite, envio ao ESP32 e páginas web. O
  painel mostra eventos, mas não envia notificações do sistema operacional.
- **ESP32:** conecta ao Wi-Fi, valida o JSON e sinaliza recebimento. Não classifica
  áudio nem conecta de volta ao Flask.
- **Túnel HTTPS:** permite ao navegador liberar o microfone e aos celulares
  acessarem o Flask. O script `iniciar.sh` gera uma senha aleatória para a
  demonstração.

Se o ESP32 estiver indisponível, o Flask mantém o evento no histórico e informa
que os LEDs não foram atualizados. O envio é local e não possui fila de
retransmissão.

## Protocolo do evento

```json
{
  "event_id": "id-unico",
  "device": "sans_phone_01",
  "event": "dog_barking",
  "description": "Cachorro latindo",
  "confidence": 0.87,
  "timestamp": "2026-11-15T12:00:00Z"
}
```

Eventos suportados nesta versão: `doorbell`, `dog_barking`, `cat_meowing`,
`clapping` e `alarm`. Os testes no notebook reconheceram gato, cachorro,
campainha e palmas. Alarmes não foram reconhecidos de forma consistente. O
funcionamento do microfone e do navegador em um celular ainda precisa ser
validado.

Veja o [README principal](../README.md) para iniciar e
[roteiro de teste](./TESTE-MANUAL.md) para validar a comunicação.
