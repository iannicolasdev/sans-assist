#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Uso: ./iniciar.sh IP_DO_ESP32" >&2
  exit 2
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared não encontrado. Instale-o seguindo a documentação oficial:" >&2
  echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
  exit 1
fi

backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/backend" && pwd)"
python="$backend_dir/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "Ambiente Python ausente. Prepare-o uma vez com:" >&2
  echo "  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

export SANS_ESP32_EVENT_URL="http://$1/event"
SANS_ACCESS_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
export SANS_ACCESS_PASSWORD

"$python" "$backend_dir/app.py" &
flask_pid=$!
trap 'kill "$flask_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sleep 1
if ! curl --fail --silent --user "sans:$SANS_ACCESS_PASSWORD" \
  http://127.0.0.1:5000/api/health >/dev/null; then
  echo "O backend não iniciou em http://127.0.0.1:5000." >&2
  exit 1
fi

echo
echo "Quando o túnel mostrar o endereço HTTPS, use-o nos dois celulares."
echo "Login do navegador: usuário sans | senha $SANS_ACCESS_PASSWORD"
echo "Sensor: ENDERECO_HTTPS/sensor | Painel do usuário: ENDERECO_HTTPS/"
echo "Não compartilhe o endereço ou a senha. Ctrl+C encerra o túnel."
echo

cloudflared tunnel --url http://127.0.0.1:5000
