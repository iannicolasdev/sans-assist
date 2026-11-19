# SANS

Sistema Acessível de Notificações Sensoriais: um protótipo que transforma
sons do ambiente em eventos visuais. O classificador de áudio roda no navegador;
o backend registra as detecções e as encaminha a um ESP32, que sinaliza o
recebimento por LEDs.


## Como funciona

```text
Microfone do notebook ou celular
        │ áudio analisado localmente
        ▼
Navegador + YAMNet
        │ evento JSON por HTTPS (sem áudio)
        ▼
Flask ───► SQLite
  │
  │ evento JSON pela rede local
  ▼
ESP32 ───► LEDs

Navegador do usuário ── HTTPS ──► Flask ──► painel de eventos
```

O dispositivo sensor processa o áudio localmente. Quando detecta um som
suportado, envia apenas o identificador do evento, a confiança e o horário.
O Flask salva o evento antes de avisar o ESP32. O painel consulta o histórico
periodicamente. Não há envio de gravações de áudio.

## Requisitos

- Python 3 e `venv`
- `cloudflared` instalado para fornecer HTTPS ao navegador
- PlatformIO Core (CLI) para compilar e gravar o ESP32
- ESP32 e computador conectados à mesma rede Wi-Fi; a placa requer Wi-Fi de
  2,4 GHz
- Internet no navegador do sensor para carregar TensorFlow.js e YAMNet na
  primeira inicialização

## Configuração inicial

### 1. Configure e grave o ESP32

Na raiz do repositório, crie o arquivo local de credenciais copiando o exemplo:

```sh
cp firmware/include/secrets.example.h firmware/include/secrets.h
```

Edite `firmware/include/secrets.h` com o nome e a senha da rede Wi-Fi. Esse
arquivo é ignorado pelo Git e **não deve ser publicado**.

Compile e grave a placa:

```sh
cd firmware
pio run -t upload
pio device monitor -b 115200
```

No monitor serial, espere a mensagem `HTTP server listening at http://.../event`
e anote o IP da placa. Se trocar de rede, o endereço pode mudar. Saia do monitor
com `Ctrl+C` antes de usar o mesmo terminal para outro comando.

### 2. Prepare o backend

Em outro terminal, na raiz do repositório:

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
```

### 3. Instale o cloudflared

Siga as instruções oficiais para seu sistema operacional:
[instalação do cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

## Iniciar o sistema

Com o ESP32 ligado e conectado ao Wi-Fi, rode na raiz:

```sh
./iniciar.sh IP_DO_ESP32
```

Por exemplo, substitua `IP_DO_ESP32` pelo endereço que apareceu no monitor
serial. O terminal mostrará uma senha temporária e, em seguida, o endereço
HTTPS criado pelo Cloudflare Tunnel. **Deixe o terminal aberto** enquanto usar
o sistema.

Abra o endereço usando usuário `sans` e a senha daquela execução:

- **Sensor de áudio:** `https://ENDERECO_DO_TUNEL/sensor`
- **Painel do usuário:** `https://ENDERECO_DO_TUNEL/`

No sensor, selecione **Iniciar monitoramento** e permita o acesso ao microfone.
O notebook pode ser usado como sensor e também como painel, abrindo as páginas
em abas diferentes. Mantenha a página do sensor em primeiro plano e a tela
ligada; navegadores podem interromper a captura quando a página fica em
segundo plano.

O endereço e a senha mudam quando o script é reiniciado. `Ctrl+C` encerra o
túnel e o backend. O endereço temporário é acessível pela Internet; mantenha a
senha privada, não inclua dados pessoais nos eventos e use o túnel apenas para
testes e demonstrações.

## Teste rápido

Antes de testar sons reais, abra o painel e use **Demonstrar sem microfone**.
O evento de simulação deve aparecer no histórico, e o ESP32 deve acender os
LEDs amarelo e verde. Depois, use a página `/sensor` para testar o
reconhecimento pelo microfone.

Para o procedimento detalhado e soluções para problemas comuns, consulte
[`docs/TESTE-MANUAL.md`](docs/TESTE-MANUAL.md).

## Organização do repositório

```text
backend/
  app.py                 API Flask, banco SQLite e páginas web
  static/                JavaScript, CSS e classes do YAMNet
  templates/             Sensor e painel
  tests/                 Testes automatizados da API
firmware/
  include/                Exemplo de configuração local do ESP32
  src/main.cpp            Servidor HTTP e controle dos LEDs
docs/
  PROJETO-SANS.md         Arquitetura e responsabilidades
  TESTE-MANUAL.md         Roteiro de execução e validação
iniciar.sh                Inicia o backend protegido e o túnel HTTPS
```

## API principal

| Método | Rota | Função |
|---|---|---|
| `GET` | `/api/health` | Verifica se o backend está ativo |
| `POST` | `/api/sensor-event` | Recebe uma detecção do navegador |
| `POST` | `/api/simulate` | Gera um evento de demonstração |
| `GET` | `/api/events` | Lista eventos registrados |
| `POST` | `/api/events` | Registra um evento JSON |
| `POST` | ESP32 `/event` | Valida evento e sinaliza os LEDs |

O SQLite é criado automaticamente em `backend/instance/events.sqlite3`; esse
banco e outros arquivos locais são ignorados pelo Git.

## Testes e compilação

Testes do backend:

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

Compilação do firmware:

```sh
cd firmware
pio run
```

## Limitações conhecidas

- YAMNet classifica categorias gerais de áudio; diferentes tipos de alarme
  podem ser classificados como música ou outra categoria.
- O limite inicial de confiança é 45%, com duas detecções seguidas e intervalo
  de 10 segundos para evitar eventos repetidos. Esses valores podem precisar
  de ajuste conforme o microfone e o ambiente.
- A página do sensor precisa permanecer aberta e em primeiro plano; não há
  captura em segundo plano nem notificações nativas do sistema operacional.
- Se o ESP32 estiver indisponível, o Flask ainda mantém o evento no histórico,
  mas os LEDs não são atualizados e não há fila de reenvio.
- A conexão do ESP32 ao Flask é HTTP na rede local. O protótipo é para uma rede
  confiável e não deve ser exposto como serviço de produção.

## Segurança e arquivos locais

Nunca publique `firmware/include/secrets.h`, certificados privados, bancos de
dados locais, senhas ou arquivos `.env`. O repositório inclui
`firmware/include/secrets.example.h` apenas como modelo sem credenciais.
