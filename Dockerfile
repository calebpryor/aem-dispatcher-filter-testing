FROM centos:8

ADD httpd-renderer.conf /etc/httpd/conf/httpd-renderer.conf

RUN yum -y --disablerepo '*' --enablerepo=extras swap centos-linux-repos centos-stream-repos

RUN yum -y --nogpgcheck install epel-release && \
    yum -y --nogpgcheck install wget openssl httpd mod_ssl supervisor && \
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

ADD start.sh /usr/local/bin/start.sh
ADD svd-apache-nc.ini /etc/supervisord.d/svd-apache-nc.ini
ADD httpd-dispatcher.conf /etc/httpd/conf.d/httpd-dispatcher.conf
ADD dispatcher.any /etc/httpd/conf.dispatcher.d/dispatcher.any
ADD 02-dispatcher.conf /etc/httpd/conf.modules.d/02-dispatcher.conf
ADD index.html /var/www/renderer/index.html

ADD openssl.cnf /tmp/openssl.cnf
RUN openssl req -x509 -out /etc/pki/tls/certs/localhost.crt -keyout /etc/pki/tls/private/localhost.key -newkey rsa:2048 -nodes -sha256 -subj '/CN=localhost' -extensions EXT -config /tmp/openssl.cnf

RUN chown -R apache:apache /var/log /var/www /run/httpd /var/run/supervisor /etc/httpd && \
    chown -R apache:apache /etc/httpd/modules/dispatcher && \
    chown apache:apache /etc/pki/tls/certs/localhost.crt && \
    chown apache:apache /etc/pki/tls/private/localhost.key
USER apache

EXPOSE 80
EXPOSE 443
CMD /usr/local/bin/start.sh $DISP_VER
