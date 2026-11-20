# Overpass API with nginx 1.31.9, the current nginx release (nginx.org mainline), and nothing else changed.
#
# Base: the wiktorn/overpass-api v0.7.62.11 build the server has run since 2026-10-23, pinned by digest
# (Debian 12, nginx 1.29.1). Upstream's newest builds (2026-11-09) carry nginx 1.31.8, which is still in
# the range of the advisories fixed in 1.31.9 / 1.30.7 (nginx.org/en/security_advisories.html), so this
# image upgrades nginx and its five module packages in place, from nginx.org's signed Debian 12 repository
# (the image's own keyring; main key 573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62). The nginx configuration
# Overpass uses is rendered from its template at every start, so it is unchanged.
#
# The deploy workflow builds it only when its tag is missing, so deploys never restart Overpass, which
# UrbanMind also uses. By hand:  docker build -t geospark-overpass:0.7.62.11-nginx-1.31.9 deploy/overpass-nginx
# Move to an upstream build once one ships nginx >= 1.31.9 (test it: it also moves to Debian 13).
FROM wiktorn/overpass-api:v0.7.62.11@sha256:5f643f2aa500333f19458fe8be14457215d6e0b9f891ca5c5ed452b1f8882c47

# ENV, not ARG: the base image sets NGINX_VERSION=1.29.1 and NJS_VERSION=0.9.1, and with the classic builder
# (the server's) an inherited ENV overrides an ARG of the same name. Setting them here also keeps the image's
# own metadata right (a scanner reading NGINX_VERSION sees the installed version).
ENV NGINX_VERSION=1.31.9 NJS_VERSION=1.0.2 NJS_RELEASE=1~bookworm
RUN set -eux; \
    echo "deb [signed-by=/etc/apt/keyrings/nginx-archive-keyring.gpg] https://nginx.org/packages/mainline/debian/ bookworm nginx" \
        > /etc/apt/sources.list.d/nginx.list; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confold \
        "nginx=${NGINX_VERSION}-1~bookworm" \
        "nginx-module-geoip=${NGINX_VERSION}-1~bookworm" \
        "nginx-module-image-filter=${NGINX_VERSION}-1~bookworm" \
        "nginx-module-njs=${NGINX_VERSION}+${NJS_VERSION}-1~bookworm" \
        "nginx-module-otel=${NGINX_VERSION}+0.1.2-1~bookworm" \
        "nginx-module-xslt=${NGINX_VERSION}-1~bookworm"; \
    rm -f /etc/apt/sources.list.d/nginx.list; \
    rm -rf /var/lib/apt/lists/*; \
    nginx -v 2>&1 | grep -F "nginx/${NGINX_VERSION}"
