# Teste manual do SANS

Este roteiro valida o caminho **Flask → ESP32 → LEDs → painel** com evento
simulado; depois, pode validar o microfone no celular.

## 1. Preparar e iniciar

- Computador e ESP32 conectados à mesma rede Wi-Fi.
- Firmware gravado e ESP32 ligado. Anote o IP atual no monitor serial.
- Ambiente Flask preparado uma vez (veja o [README](../README.md)).
- Na raiz do projeto:

  ```sh
  ./iniciar.sh IP_DO_ESP32
  ```

O terminal informa o endereço HTTPS e a senha da sessão. Mantenha-o aberto.
Em outro terminal, confirme o backend:

```sh
curl -u "sans:SENHA_MOSTRADA_NO_TERMINAL" \
  http://127.0.0.1:5000/api/health
```

Como o TLS termina no túnel, o backend local usa HTTP. Para um teste local sem
o túnel, rode em `backend/`:

```sh
SANS_ESP32_EVENT_URL="http://IP_DO_ESP32/event" .venv/bin/python app.py
```

Consulte `http://127.0.0.1:5000`; o navegador não liberará o microfone nesse
modo.

## 2. Simular pelo painel

Abra o endereço HTTPS no celular do usuário ou no computador, entre com usuário
`sans` e a senha do terminal e use **Demonstrar sem microfone**.

Resultado esperado:

- A mensagem informa que o evento foi salvo e o ESP32 avisado.
- O LED amarelo acende por cerca de 700 ms e o verde por até 3 segundos.
- O evento aparece no histórico em até 5 segundos.

## 3. Enviar evento manual pelo Flask

Com o túnel iniciado, substitua `SENHA` pela senha temporária exibida:

```sh
curl -u "sans:SENHA" -i -X POST http://127.0.0.1:5000/api/sensor-event \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "manual-test-001",
    "event": "cat_meowing",
    "confidence": 0.94,
    "timestamp": "2026-11-15T22:00:00Z"
  }'
```

O JSON de resposta deve ter `"success": true` e `"esp32_notified": true`.
Consulte `GET /api/events` para confirmar que o evento foi gravado.

## 4. Testar o microfone

No dispositivo sensor (notebook ou celular), abra `ENDERECO_HTTPS/sensor`,
autentique, toque em **Iniciar monitoramento** e permita o microfone. Faça
palmas ou reproduza um latido perto do microfone. Verifique a lista de classes
reconhecidas e, depois, o envio, os LEDs e o painel. Mantenha a página em
primeiro plano e a tela ligada.

O modelo YAMNet pode não reconhecer todos os sons; ajuste a confiança mínima.
Esse teste físico não pode ser substituído pela suíte automática.

## Se o evento não chegar

- **Histórico tem evento, ESP32 não acendeu:** confira o IP do ESP32 no monitor
  serial e reinicie `./iniciar.sh` com o endereço correto. O evento não é perdido
  no histórico.
- **HTTP 401:** use usuário `sans` e a senha mostrada pelo processo atual.
- **Microfone bloqueado:** confirme que abriu o endereço HTTPS do túnel, não o
  endereço `http://` local.
- **Flask não inicia:** confira o ambiente Python em `backend/.venv` e se a
  porta 5000 está livre.
- **O ESP32 responde sozinho, mas não aparece no histórico:** o caminho de teste
  é pelo Flask/painel. O `POST /event` direto na placa apenas testa os LEDs.

Para encerrar a demonstração, pressione `Ctrl+C` no terminal do túnel.
