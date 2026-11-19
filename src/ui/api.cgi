#!/bin/sh
# SynetScan API endpoint – authenticates the DSM session and forwards to synetscand.
DIR=$(cd "$(dirname "$0")" && pwd -P)
LIB="$DIR/../lib"
PY=""
for c in /var/packages/Python3.9/target/usr/bin/python3 /usr/local/bin/python3 /usr/bin/python3 /bin/python3; do
    if [ -x "$c" ]; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    printf 'Status: 500 Internal Server Error\r\nContent-Type: application/json\r\n\r\n'
    printf '{"success":false,"error":{"code":"python","message":"Python 3 not found"}}'
    exit 0
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$PY" -I -c "import sys; sys.path.insert(0, sys.argv[1]); from synetscan.cgi_main import main; main()" "$LIB"
