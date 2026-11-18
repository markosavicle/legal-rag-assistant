#!/usr/bin/env bash
# Index the public Labour Law and the fictional sample contracts, then ask the demo questions.
# Usage: ./examples/demo/run_demo.sh [base-url]   (default http://localhost:8000)
# Needs: the API running (docker compose up), curl, jq. Put Zakon o radu PDF at data/zakon_o_radu.pdf
# (official consolidated text, e.g. from paragraf.rs or pravno-informacioni-sistem.rs).
# Set API_KEY in the environment if the server requires one.
set -euo pipefail
BASE="${1:-http://localhost:8000}"
AUTH=(); [[ -n "${API_KEY:-}" ]] && AUTH=(-H "X-API-Key: $API_KEY")
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

for f in "$ROOT"/data/zakon_o_radu.pdf "$ROOT"/samples/*.txt; do
  [[ -f "$f" ]] || { echo "skip (missing): $f"; continue; }
  code=$(curl -s -o /dev/null -w '%{http_code}' "${AUTH[@]}" -F "file=@$f" "$BASE/documents")
  echo "upload $(basename "$f"): HTTP $code (409 = already indexed)"
done

ask() {
  echo; echo "Q: $1"
  curl -s "${AUTH[@]}" -X POST "$BASE/ask" -H 'Content-Type: application/json' \
       -d "$(jq -n --arg q "$1" '{question: $q}')" \
    | jq -r '"A: \(.answer)\n   answered=\(.answered)  cites=\([.citations[] as $c | .sources[] | select(.n == $c) | .source] | join("; "))  \(.latency_ms) ms"'
}

ask "Koliko najmanje traje godišnji odmor?"
ask "Колико по правилу траје радна недеља?"
ask "Koliko dana godišnjeg odmora ima Ana Jović?"
ask "Da li je godišnji odmor od 18 radnih dana iz aneksa ugovora Ane Jović u skladu sa Zakonom o radu?"
ask "Pošto zakon dozvoljava probni rad od godinu dana, da li poslodavac može da ugovori probni rad od 10 meseci?"
ask "Kolika je neto zarada Nikole Ilića?"
ask "Koja je kazna za prebrzu vožnju?"
