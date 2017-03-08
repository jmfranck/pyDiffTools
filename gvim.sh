#!/bin/bash
# for sumatra, use:
# "C:\Program Files (x86)\Vim\vim80\gvim.exe" --remote-wait-silent +%l %f 
gvimloc="c:\\Program Files (x86)\\Vim\\vim80"
if [ $# -gt 1 ]; then
	"$gvimloc" $*
else
	#filename=$(echo "$1" | sed 's/^\/\([a-z]\)\//\1:\//')
    #"$gvimloc\\gvim.exe" -c ":RemoteOpen $filename|cd %:h" &
	# works for one file, but still not for diff
	servers=$("$gvimloc\\vim.exe" "--serverlist")
	echo "servers are $servers"
	if [[ $servers == *"GVIM"* ]]; then
		"$gvimloc\\gvim.exe" --remote $* &
	else
		"$gvimloc\\gvim.exe" --servername gvim &
		until [[ $servers == *"GVIM"* ]]; do
			echo "server should be open"
			servers=$("$gvimloc\\vim.exe" "--serverlist")
		done
		"$gvimloc\\gvim.exe" --remote $* &
	fi
fi
