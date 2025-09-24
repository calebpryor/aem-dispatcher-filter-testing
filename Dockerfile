FROM rockylinux:8
RUN dnf -y --nogpgcheck install epel-release && \
    dnf -y --nogpgcheck install wget httpd supervisor inotify-tools && \
    dnf clean all
RUN mkdir -p /run/httpd && \
    mkdir -p /var/run/supervisor && \
    mkdir -p /etc/httpd/conf.dispatcher.d/filters && \
    mkdir -p /etc/httpd/modules/dispatcher && \
    mkdir -p /var/www/renderer && \
    ln -sf /dev/stdout /var/log/httpd/access_log && \
    ln -sf /dev/stderr /var/log/supervisord.log && \
    ln -sf /dev/stderr /var/log/httpd/error_log
RUN setcap 'cap_net_bind_service=+ep' /usr/sbin/httpd && \
    setcap 'cap_net_bind_service=+ep' /usr/bin/supervisord
ADD services/start.sh /usr/local/bin/start.sh
ADD services/watch_filters.sh /usr/local/bin/watch_filters.sh
ADD services/filter_log_extractor.sh /usr/local/bin/filter_log_extractor.sh
ADD services/svd-apache-nc.ini /etc/supervisord.d/svd-apache-nc.ini
RUN chmod +x /usr/local/bin/start.sh /usr/local/bin/watch_filters.sh /usr/local/bin/filter_log_extractor.sh
ADD apache/httpd-renderer.conf /etc/httpd/conf/httpd-renderer.conf
ADD apache/httpd-dispatcher.conf /etc/httpd/conf.d/httpd-dispatcher.conf
ADD apache/dispatcher.any /etc/httpd/conf.dispatcher.d/dispatcher.any
ADD apache/02-dispatcher.conf /etc/httpd/conf.modules.d/02-dispatcher.conf
ADD www/container-404.html /var/www/renderer/container-404.html
ADD www/index.html /var/www/renderer/index.html
ADD www/test.json /var/www/renderer/test.json
ADD www/test.xml /var/www/renderer/test.xml
ADD www/image.jpg /var/www/renderer/image.jpg
ADD www/image.png /var/www/renderer/image.png
ADD www/image.gif /var/www/renderer/image.gif
RUN chown -R apache:apache /var/log /var/www /run/httpd /var/run/supervisor /etc/httpd && \
    chown -R apache:apache /etc/httpd/modules/dispatcher
USER apache
EXPOSE 80
CMD ["/bin/bash", "-c", "/usr/local/bin/start.sh ${DISP_VER:-4.3.7}"]
