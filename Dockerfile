FROM centos:latest

ADD start-nc.sh /usr/local/bin/start-nc.sh

RUN chmod +x /usr/local/bin/start-nc.sh && \
    yum -y --nogpgcheck install epel-release && \
    yum -y --nogpgcheck install httpd mod_ssl nc supervisor && \
    yum clean all

RUN mkdir -p /run/httpd && \
    mkdir -p /var/run/supervisor && \
    mkdir -p /etc/httpd/conf.dispatcher.d/filters && \
    mkdir -p /etc/httpd/modules/dispatcher && \
    ln -sf /dev/stdout /var/log/httpd/access_log && \
    ln -sf /dev/stdout /var/log/httpd/dispatcher.log && \
    ln -sf /dev/stderr /var/log/supervisord.log && \
    ln -sf /dev/stderr /var/log/httpd/error_log

RUN setcap 'cap_net_bind_service=+ep' /usr/sbin/httpd && \
    setcap 'cap_net_bind_service=+ep' /usr/local/bin/start-nc.sh && \
    setcap 'cap_net_bind_service=+ep' /usr/bin/supervisord

ADD svd-apache-nc.ini /etc/supervisord.d/svd-apache-nc.ini
ADD httpd-dispatcher.conf /etc/httpd/conf.d/httpd-dispatcher.conf
ADD dispatcher.any /etc/httpd/conf.dispatcher.d/dispatcher.any
ADD 02-dispatcher.conf /etc/httpd/conf.modules.d/02-dispatcher.conf

RUN chown -R apache:apache /var/log /run/httpd /var/run/supervisor /etc/httpd && \
    chown apache:apache /etc/pki/tls/certs/localhost.crt && \
    chown apache:apache /etc/pki/tls/private/localhost.key

USER apache

EXPOSE 80
EXPOSE 443
CMD /usr/bin/supervisord -j /var/run/supervisor/supervisord.pid