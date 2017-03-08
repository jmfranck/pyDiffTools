#!/bin/bash
if [ $# -gt 1 ]; then
	"c:\\Program Files (x86)\\Vim\\vim80\\gvim.exe" $*
else
	#filename=$(echo "$1" | sed 's/^\/\([a-z]\)\//\1:\//')
        #"c:\\Program Files (x86)\\Vim\\vim80\\gvim.exe" -c ":RemoteOpen $filename|cd %:h" &
	# works for one file, but still not for diff
	servers=$("c:\\Program Files (x86)\\Vim\\vim80\\vim.exe" "--serverlist")
	echo "servers are $servers"
	if [[ $servers == *"GVIM"* ]]; then
		"c:\\Program Files (x86)\\Vim\\vim80\\gvim.exe" --remote $* &
	else
		"c:\\Program Files (x86)\\Vim\\vim80\\gvim.exe" --servername gvim &
		until [[ $servers == *"GVIM"* ]]; do
			echo "server should be open"
			servers=$("c:\\Program Files (x86)\\Vim\\vim80\\vim.exe" "--serverlist")
		done
		"c:\\Program Files (x86)\\Vim\\vim80\\gvim.exe" --remote $* &
	fi
fi
