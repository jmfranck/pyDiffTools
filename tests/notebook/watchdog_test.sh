#!/bin/bash
set -e
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT
export PYDIFFTOOLS_FAKE_MATHJAX=1
python3 -m pydifftools.command_line qmdinit "$TMP_DIR" >/dev/null
cd "$TMP_DIR"
python3 -u -m pydifftools.command_line qmdb --watch --no-browser > /tmp/watchdog.log 2>&1 &
PID=$!
sleep 5
MARK="WATCHDOG_TEST_$(date +%s)"
sed -i.bak "s/exploratory analysis./exploratory analysis $MARK/" project1/subproject1/tasks.qmd
sleep 5
kill $PID || true
mv project1/subproject1/tasks.qmd.bak project1/subproject1/tasks.qmd
grep -q "$MARK" _build/project1/subproject1/tasks.html
