FROM quay.io/keycloak/keycloak:26.7.2 AS builder

RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true

FROM quay.io/keycloak/keycloak:26.7.2

COPY --from=builder /opt/keycloak/ /opt/keycloak/

USER 1000
