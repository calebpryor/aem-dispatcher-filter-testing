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
		echo "$desc" | grep -q "x86-64" || exit 1
		;;
	aarch64)
		echo "$desc" | grep -q "aarch64" || exit 1
		;;
	*)
		;;
esac
# Check shared library dependencies — catches glibc version mismatches
# (e.g. module built for RHEL9 requiring GLIBC_2.32 run on RHEL/Rocky 8)
ldd_out=$(ldd "$MOD" 2>&1)
if echo "$ldd_out" | grep -q "not found"; then
	echo "Library dependency check failed for $MOD:" >&2
	echo "$ldd_out" >&2
	exit 1
fi
exit 0
