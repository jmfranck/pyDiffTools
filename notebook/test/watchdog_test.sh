#!/bin/bash
set -e
python3 -u fast_build.py --watch --no-browser > /tmp/watchdog.log 2>&1 &
PID=$!
# give the server time to start
sleep 5
# add a unique marker
MARK="WATCHDOG_TEST_$(date +%s)"
# replace existing text so the change is deterministic
sed -i.bak "s/exploratory analysis./exploratory analysis $MARK/" project1/subproject1/tasks.qmd
# wait for rebuild
sleep 5
kill $PID
# restore original file
mv project1/subproject1/tasks.qmd.bak project1/subproject1/tasks.qmd
# verify the marker appears in built HTML
grep -q "$MARK" _build/projects.html
