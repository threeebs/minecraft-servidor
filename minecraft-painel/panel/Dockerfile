
FROM php:8.3-apache

# Executar o Apache com o mesmo UID/GID do Minecraft
RUN usermod -u 1000 www-data \
    && groupmod -g 1000 www-data

RUN apt-get update \
    && apt-get install -y \
       --no-install-recommends \
       tar ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && a2enmod headers \
    && printf '%s\n' \
       'ServerTokens Prod' \
       'ServerSignature Off' \
       >> /etc/apache2/conf-available/security.conf

COPY index.php rcon.php updates.php console.js updates.js /var/www/html/

RUN mkdir -p /var/lib/php/sessions \
    && chown -R www-data:www-data /var/www/html /var/lib/php/sessions \
    && chmod 700 /var/lib/php/sessions \
    && printf '%s\n' 'session.save_path=/var/lib/php/sessions' > /usr/local/etc/php/conf.d/panel-sessions.ini
