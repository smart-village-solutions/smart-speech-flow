package org.smartspeechflow.keycloak;

import java.util.List;
import org.keycloak.OAuth2Constants;
import org.keycloak.models.ClientModel;
import org.keycloak.models.ClientSessionContext;
import org.keycloak.models.Constants;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.ProtocolMapperModel;
import org.keycloak.models.UserSessionModel;
import org.keycloak.protocol.oidc.mappers.AbstractOIDCProtocolMapper;
import org.keycloak.protocol.oidc.mappers.OIDCAccessTokenMapper;
import org.keycloak.provider.ProviderConfigProperty;
import org.keycloak.representations.AccessToken;
import org.keycloak.services.managers.AuthenticationManager;

/** Keep the original assurance when the standard exchange attaches an empty authentication session. */
public final class RecordingExchangeAssuranceMapper extends AbstractOIDCProtocolMapper implements OIDCAccessTokenMapper {
    @Override public String getId() { return "ssf-exchange-assurance-mapper"; }
    @Override public String getDisplayType() { return "SSF recording exchange assurance"; }
    @Override public String getDisplayCategory() { return TOKEN_MAPPER_CATEGORY; }
    @Override public String getHelpText() { return "Preserves verified human session assurance for the configured recording audience."; }
    @Override public List<ProviderConfigProperty> getConfigProperties() {
        return List.of(new ProviderConfigProperty("gateway.audience", "Gateway audience",
            "Single recording API audience for this tenant.", ProviderConfigProperty.STRING_TYPE, "ssf-frontend"));
    }
    // Audience and built-in ACR mappers run first.
    @Override public int getPriority() { return 1000; }

    @Override public AccessToken transformAccessToken(AccessToken result, ProtocolMapperModel mapper,
            KeycloakSession session, UserSessionModel userSession, ClientSessionContext clientSession) {
        if (!OAuth2Constants.TOKEN_EXCHANGE_GRANT_TYPE.equals(clientSession.getAttribute(Constants.GRANT_TYPE, String.class))) {
            return result;
        }
        String audience = mapper.getConfig().get("gateway.audience");
        var context = session.getContext();
        var form = context.getHttpRequest().getDecodedFormParameters();
        var requested = form.get("audience");
        if (audience == null || requested == null || !requested.contains(audience)) return result;
        ClientModel client = clientSession.getClientSession().getClient();
        if (requested.size() != 1 || client.isPublicClient() || !result.hasAudience(audience)
                || !OAuth2Constants.ACCESS_TOKEN_TYPE.equals(form.getFirst("subject_token_type"))
                || !OAuth2Constants.ACCESS_TOKEN_TYPE.equals(form.getFirst("requested_token_type"))) {
            throw invalidBinding();
        }

        // Re-verify the signed subject token with Keycloak's own standard exchange verifier,
        // including active realm, signing key, expiry, revocation, client and online user session.
        var verified = AuthenticationManager.verifyIdentityToken(session, context.getRealm(), context.getUri(),
                context.getConnection(), true, true, audience, false, form.getFirst("subject_token"),
                context.getRequestHeaders(), verifier -> {});
        if (verified == null || verified.session() == null || verified.session().isOffline()
                || verified.user().getServiceAccountClientLink() != null) throw invalidBinding();
        AccessToken original = verified.token();
        String acceptedId = clientSession.getClientSession().getNote(Constants.TOKEN_EXCHANGE_SUBJECT_CLIENT + client.getClientId());
        if (original.getId() == null || !original.getId().equals(acceptedId)
                || !client.getClientId().equals(original.getIssuedFor()) || !client.getClientId().equals(result.getIssuedFor())
                || !userSession.getId().equals(verified.session().getId()) || !userSession.getId().equals(original.getSessionId())
                || !userSession.getId().equals(result.getSessionId()) || !verified.user().getId().equals(result.getSubject())
                || !verified.user().getId().equals(original.getSubject()) || !original.getIssuer().equals(result.getIssuer())
                || original.getAcr() == null || original.getAuth_time() == null) throw invalidBinding();
        result.setAcr(original.getAcr());
        result.setAuth_time(original.getAuth_time());
        return result;
    }

    private static IllegalStateException invalidBinding() {
        return new IllegalStateException("SSF recording exchange identity binding failed");
    }
}
