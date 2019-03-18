## Place holder
This is where you'll put the dispatcher .so file
name it mod_dispatcher.so and drop it in this file.
When you do the docker run command you'll use the -v option like:
```docker run -d -p 80:80 -v <FOLDER WHERE YOU PUT THE .so FILE>:/etc/httpd/modules/dispatcher/ <IMAGE NAME>```