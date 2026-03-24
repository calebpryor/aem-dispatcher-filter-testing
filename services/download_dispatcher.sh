#!/bin/bash
# Download Adobe dispatcher mod_dispatcher.so for Apache 2.4 (Linux) into the
# runtime path. Intended for container use; module is not baked into the image.
MODULE_VER="${1:-4.3.8}"
CPU_ARCH="$(uname -m)"
TARGET="/etc/httpd/modules/dispatcher/mod_dispatcher.so"

case "$MODULE_VER" in
	4.3.3)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.3.tar.gz"
		;;
	4.3.4)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.4.tar.gz"
		;;
	4.3.5)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.5.tar.gz"
		;;
	4.3.6)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.6.tar.gz"
		;;
	4.3.7)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.7.tar.gz"
		;;
	4.3.8)
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.8.tar.gz"
		;;
	*)
		echo "Unknown dispatcher version '${MODULE_VER}', using 4.3.8 tarball" >&2
		DOWNLOAD_URL="https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-${CPU_ARCH}-4.3.8.tar.gz"
		;;
esac

cd /tmp
rm -f dispatcher-apache2.4-linux-*.tar.gz
echo "Downloading dispatcher module from ${DOWNLOAD_URL}"
wget "$DOWNLOAD_URL" || exit 1
echo "Extracting .so to $(dirname "$TARGET")/"
tar -xvf dispatcher-apache2.4-linux-*.tar.gz --wildcards --no-anchored '*.so'
tar xzf dispatcher-apache2.4-*.tar.gz
cp -v dispatcher-*.so "$TARGET"

echo "Installed ${TARGET} (version ${MODULE_VER})"
