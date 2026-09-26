#!/bin/bash
export PATH=/root/depot_tools:$PATH DEPOT_TOOLS_UPDATE=0
cd /root/cr153/src
autoninja -C out/Omt "$@"
