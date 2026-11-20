#!/usr/bin/env sh
# Overpass's update loop (update_overpass_loop.sh from wiktorn/overpass-api v0.7.62.11), with one change:
# the first run waits until the query service (dispatcher) answers.
#
# Why: update_overpass.sh asks once per run whether the dispatcher is up. At container start supervisord
# starts this loop ~10 ms after the dispatcher, so the first run could ask too early, try to update the
# database directly, and be refused ("...indicates a running dispatcher"). The change file was kept and
# applied an hour later, so no data was lost, only time. Waiting at most 120 s fixes that; if the
# dispatcher never answers, the run goes ahead exactly as before.
#
# The server's docker-compose.override.yml mounts this file over /app/bin/update_overpass_loop.sh
# (read-only). Keep the path, or change the mount with it.

OVERPASS_UPDATE_SLEEP=${OVERPASS_UPDATE_SLEEP:-60}

waited=0
while /app/bin/dispatcher --show-dir | grep -q File_Error && [ "$waited" -lt 120 ]; do
	sleep 2
	waited=$((waited + 2))
done
echo "update loop: dispatcher check done after ${waited} s"

set +e
while true; do
	if [ -n "$OVERPASS_DIFF_URL" ]; then
		/app/bin/update_overpass.sh
	fi
	sleep "${OVERPASS_UPDATE_SLEEP}"
done
