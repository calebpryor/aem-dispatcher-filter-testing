#!/bin/bash
#cleanup () {
#	kill $!
#	exit 0
#}

#trap cleanup SIGINT

#/usr/sbin/httpd -D FOREGROUND
while true; do 
	nc -l -p 4503 -c 'echo -e "HTTP/1.1 200 OK\n\n YOUR FILTER LET YOU THROUGH"'
done
