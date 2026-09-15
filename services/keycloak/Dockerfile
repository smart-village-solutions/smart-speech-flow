FROM quay.io/keycloak/keycloak:26.7.2 AS builder

RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true

FROM quay.io/keycloak/keycloak:26.7.2

COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY services/keycloak/theme /opt/keycloak/themes/kasseldialog/
COPY services/frontend/public/assets/Logo.png /opt/keycloak/themes/kasseldialog/login/resources/img/header-logo.png
COPY services/frontend/public/assets/Foerdermittelgeber.png /opt/keycloak/themes/kasseldialog/login/resources/img/footer-funding.png
COPY services/frontend/public/assets/Stadt.png /opt/keycloak/themes/kasseldialog/login/resources/img/footer-city.png
COPY services/frontend/public/fonts/Inter-Variable.woff2 /opt/keycloak/themes/kasseldialog/login/resources/fonts/Inter-Variable.woff2

USER 1000
