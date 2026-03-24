#!/bin/bash
# Exit 0 if /etc/httpd/modules/dispatcher/mod_dispatcher.so is a usable Linux ELF
# shared library for this container's CPU. Used by wait_httpd.sh and the control API.
MOD="/etc/httpd/modules/dispatcher/mod_dispatcher.so"
CPU_ARCH=$(uname -m)
if [ ! -s "$MOD" ]; then
	exit 1
fi
desc=$(file -b "$MOD" 2>/dev/null) || exit 1
echo "$desc" | grep -q "ELF" || exit 1
echo "$desc" | grep -q "shared object" || exit 1
case "$CPU_ARCH" in
	x86_64)
		echo "$desc" | grep -q "x86-64" && exit 0
		exit 1
		;;
	aarch64)
		echo "$desc" | grep -q "aarch64" && exit 0
		exit 1
		;;
	*)
		exit 0
		;;
esac
