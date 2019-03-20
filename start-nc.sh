#!/bin/bash
while true; do 
	nc -l -p 4503 -c 'echo -e "HTTP/1.1 200 OK\n\n YOUR FILTER LET YOU THROUGH"'
done
