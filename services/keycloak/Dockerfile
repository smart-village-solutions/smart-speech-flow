# Keycloak 26.8.1, pinned by digest.
FROM quay.io/keycloak/keycloak@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b AS keycloak-base

# Compile against the exact server distribution shipped in the final image.
FROM eclipse-temurin:21-jdk@sha256:db5cc6341a1d7bc40cdb51e1f0d9824f3bb2cc8107d29da421dc4df7d11f05f1 AS mapper
COPY --from=keycloak-base /opt/keycloak/lib/lib/main /tmp/keycloak-libs
COPY services/keycloak/recording-exchange /src
RUN mkdir -p /classes && javac --release 21 -cp '/tmp/keycloak-libs/*' -d /classes /src/RecordingExchangeAssuranceMapper.java \
    && jar --create --file /tmp/ssf-recording-exchange.jar -C /classes . -C /src META-INF

FROM keycloak-base AS builder
COPY --from=mapper /tmp/ssf-recording-exchange.jar /opt/keycloak/providers/


RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true

FROM quay.io/keycloak/keycloak@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b

COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY services/keycloak/theme /opt/keycloak/themes/kasseldialog/
COPY services/frontend/src/ui/styles/theme.css /opt/keycloak/themes/kasseldialog/login/resources/css/theme.css
COPY services/frontend/public/assets/Logo.png /opt/keycloak/themes/kasseldialog/login/resources/img/header-logo.png
COPY services/frontend/public/assets/Foerdermittelgeber.png /opt/keycloak/themes/kasseldialog/login/resources/img/footer-funding.png
COPY services/frontend/public/assets/Stadt.png /opt/keycloak/themes/kasseldialog/login/resources/img/footer-city.png
COPY services/frontend/public/fonts/Inter-Variable.woff2 /opt/keycloak/themes/kasseldialog/login/resources/fonts/Inter-Variable.woff2

USER 1000
