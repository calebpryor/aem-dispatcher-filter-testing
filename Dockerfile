FROM centos:latest

ADD httpd-renderer.conf /etc/httpd/conf/httpd-renderer.conf

RUN yum -y --nogpgcheck install epel-release && \
    yum -y --nogpgcheck install httpd mod_ssl supervisor && \
    yum clean all

RUN mkdir -p /run/httpd && \
    mkdir -p /var/run/supervisor && \
    mkdir -p /etc/httpd/conf.dispatcher.d/filters && \
    mkdir -p /etc/httpd/modules/dispatcher && \
    mkdir -p /var/www/renderer && \
    ln -sf /dev/stdout /var/log/httpd/access_log && \
    ln -sf /dev/stdout /var/log/httpd/dispatcher.log && \
    ln -sf /dev/stderr /var/log/supervisord.log && \
    ln -sf /dev/stderr /var/log/httpd/error_log

RUN setcap 'cap_net_bind_service=+ep' /usr/sbin/httpd && \
    setcap 'cap_net_bind_service=+ep' /usr/bin/supervisord

ADD svd-apache-nc.ini /etc/supervisord.d/svd-apache-nc.ini
ADD httpd-dispatcher.conf /etc/httpd/conf.d/httpd-dispatcher.conf
ADD dispatcher.any /etc/httpd/conf.dispatcher.d/dispatcher.any
ADD 02-dispatcher.conf /etc/httpd/conf.modules.d/02-dispatcher.conf
ADD index.html /var/www/renderer/index.html

RUN chown -R apache:apache /var/log /var/www /run/httpd /var/run/supervisor /etc/httpd && \
    chown apache:apache /etc/pki/tls/certs/localhost.crt && \
    chown apache:apache /etc/pki/tls/private/localhost.key

USER apache

EXPOSE 80
EXPOSE 443
CMD /usr/bin/supervisord -j /var/run/supervisor/supervisord.pid
