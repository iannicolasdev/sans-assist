# Backend SANS

Flask centraliza o projeto: recebe eventos JSON, grava-os no SQLite, avisa o
ESP32 pela rede local e serve as páginas do sensor e do painel.

## Executar

Prepare o ambiente uma vez:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Para executar somente na rede local:

```sh
SANS_ESP32_EVENT_URL="http://IP_DO_ESP32/event" .venv/bin/python app.py
```

O servidor fica em `http://127.0.0.1:5000`. Para liberar o microfone do
navegador, use o túnel HTTPS descrito no [README principal](../README.md) e
`../iniciar.sh`.

## Endpoints

- `GET /api/health` — estado do backend.
- `POST /api/sensor-event` — recebe `{event_id, event, confidence, timestamp}`,
  registra o evento e tenta avisar o ESP32. O sucesso do registro é independente
  da conexão com os LEDs.
- `POST /api/simulate` — cria evento de demonstração e usa o mesmo fluxo.
- `POST /api/events` — recebe e registra um evento JSON completo.
- `GET /api/events` — lista eventos recentes.
- `GET /sensor` — classificador YAMNet no navegador.
- `GET /` — painel do usuário, atualizado a cada 5 segundos.

Eventos aceitos pelo sensor: `doorbell`, `dog_barking`, `cat_meowing`,
`clapping` e `alarm`. O áudio fica no navegador; o Flask recebe somente os
metadados do evento.

## Acesso pelo túnel

`iniciar.sh` gera uma senha aleatória e protege todas as páginas e APIs com
autenticação HTTP Basic enquanto o túnel está aberto. Não execute esse servidor
de desenvolvimento exposto à Internet sem essa proteção.

## Testes

```sh
.venv/bin/python -m unittest discover -s tests -v
```
