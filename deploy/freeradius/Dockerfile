# FreeRADIUS 3.2 (official image) with rlm_rest, configured for the Bessel Guest Wi-Fi backend.
FROM freeradius/freeradius-server:3.2.5
# Remove default virtual servers and EAP (FortiGate captive portal uses PAP inside RADIUS)
RUN rm -f /etc/raddb/sites-enabled/* /etc/raddb/mods-enabled/eap
COPY raddb/clients.conf /etc/raddb/clients.conf
COPY raddb/mods-enabled/rest /etc/raddb/mods-enabled/rest
COPY raddb/sites-enabled/guestwifi /etc/raddb/sites-enabled/guestwifi
EXPOSE 1812/udp 1813/udp
# Status-Server probe from the local client definition
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD echo "Message-Authenticator = 0x00" | radclient -q -t 3 -r 1 127.0.0.1:1812 status "$RADIUS_SECRET_LOCAL" || exit 1
# The image entrypoint prepends the daemon name when the first argument starts with '-'
CMD ["-f", "-l", "stdout"]
