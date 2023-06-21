#!/bin/bash
MODULE_VER=${1:-4.3.5}
CPU_ARCH=$(uname -m)

if [ ! -z "$CPU_ARCH" ];then
	case $MODULE_VER in
		4.3.3)
			DOWNLOAD_URL=https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-$CPU_ARCH-4.3.3.tar.gz
			;;
		4.3.4)
			DOWNLOAD_URL=https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-$CPU_ARCH-4.3.4.tar.gz
			;;
		4.3.5)
			DOWNLOAD_URL=https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-$CPU_ARCH-4.3.5.tar.gz
			;;
		*)
			DOWNLOAD_URL=https://download.macromedia.com/dispatcher/download/dispatcher-apache2.4-linux-$CPU_ARCH-4.3.5.tar.gz
			;;
	esac		

	if [ ! -f /etc/httpd/modules/dispatcher/mod_dispatcher.so ];then
		cd /tmp
		echo "downloading dispatcher module from url $DOWNLOAD_URL"
		wget $DOWNLOAD_URL
		echo "extracting .so to /etc/httpd/modules/dispatcher/"
		tar -xvf dispatcher-apache2.4-linux-*.tar.gz --wildcards --no-anchored '*.so'
		tar xzf dispatcher-apache2.4-*.tar.gz
		cp -v dispatcher-*.so /etc/httpd/modules/dispatcher/mod_dispatcher.so
	else
		echo "Existing dispatcher modules found"
	fi

	/usr/bin/supervisord -j /var/run/supervisor/supervisord.pid
else
	echo "UNKNOWN CPU ARCH.  ABORTING"
	exit
fi