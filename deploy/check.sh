#!/usr/bin/env sh
set -u
PORT="${1:-8000}"
KEY="${PERSIAN_OCR_API_KEY:-}"
cd "$(dirname "$0")"

fail() { echo "FAIL: $1"; docker logs --tail 40 persian-ocr-check; docker rm -f persian-ocr-check >/dev/null; exit 1; }

docker image inspect persian-ocr:0.2.0 >/dev/null 2>&1 || docker load -i persian-ocr-0.2.0.tar
docker rm -f persian-ocr-check >/dev/null 2>&1
docker run -d --name persian-ocr-check -p "$PORT:8000" -e "PERSIAN_OCR_API_KEY=$KEY" persian-ocr:0.2.0 >/dev/null

i=0
while [ $i -lt 48 ]; do
  sleep 5
  state=$(docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' persian-ocr-check)
  echo "container: $state"
  case "$state" in exited*) fail "container exited";; "running healthy") break;; esac
  i=$((i + 1))
done
[ "$state" = "running healthy" ] || fail "not healthy after 240 s"

BASE="http://127.0.0.1:$PORT"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/app")" = "200" ] || fail "/app did not return 200"
chars=$(curl -s -H "X-API-Key: $KEY" -F "file=@test-invoice.png" "$BASE/ocr/text?lexicon=false" | wc -c)
[ "$chars" -ge 500 ] || fail "/ocr/text returned no text"
echo "OK: healthy, /app 200, /ocr/text $chars bytes"
docker rm -f persian-ocr-check >/dev/null
