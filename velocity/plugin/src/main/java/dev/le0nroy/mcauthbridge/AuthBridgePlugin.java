package dev.le0nroy.mcauthbridge;

import com.google.gson.JsonObject;
import com.google.inject.Inject;
import com.velocitypowered.api.event.EventTask;
import com.velocitypowered.api.event.Subscribe;
import com.velocitypowered.api.event.connection.DisconnectEvent;
import com.velocitypowered.api.event.connection.PreLoginEvent;
import com.velocitypowered.api.event.player.GameProfileRequestEvent;
import com.velocitypowered.api.plugin.Plugin;
import com.velocitypowered.api.proxy.ProxyServer;
import com.velocitypowered.api.util.GameProfile;
import net.kyori.adventure.text.Component;
import org.slf4j.Logger;

import java.io.IOException;
import java.util.concurrent.ConcurrentHashMap;

@Plugin(
    id = "mc-auth-bridge",
    name = "MC Auth Bridge",
    version = "1.0.0",
    description = "Velocity plugin that gates logins via the auth identity sidecar",
    authors = {"le0nroy"}
)
public class AuthBridgePlugin {

    private static final String DEFAULT_AUTH_SIDECAR_URL = "http://host.docker.internal:8181";
    private static final int HTTP_TIMEOUT_MS = 5000;

    private final ProxyServer proxy;
    private final Logger logger;
    private final AuthSidecarClient sidecarClient;
    final ConcurrentHashMap<String, JsonObject> pendingIdentities = new ConcurrentHashMap<>();

    @Inject
    public AuthBridgePlugin(ProxyServer proxy, Logger logger) {
        this.proxy = proxy;
        this.logger = logger;
        String url = System.getenv().getOrDefault("AUTH_SIDECAR_URL", DEFAULT_AUTH_SIDECAR_URL);
        this.sidecarClient = new AuthSidecarClient(url, HTTP_TIMEOUT_MS);
        proxy.getEventManager().register(this, this);
        logger.info("mc-auth-bridge loaded, sidecar={}", url);
    }

    // Package-private for testing — accepts pre-built client, still registers events.
    AuthBridgePlugin(ProxyServer proxy, Logger logger, AuthSidecarClient client) {
        this.proxy = proxy;
        this.logger = logger;
        this.sidecarClient = client;
        proxy.getEventManager().register(this, this);
    }

    @Subscribe
    public EventTask onPreLogin(PreLoginEvent event) {
        return EventTask.async(() -> {
            String username = event.getUsername();
            String ip = event.getConnection().getRemoteAddress().getAddress().getHostAddress();
            processPreLogin(username, ip, event);
        });
    }

    void processPreLogin(String username, String ip, PreLoginEvent event) {
        logger.info("PreLogin username={} ip={}", username, ip);

        JsonObject response;
        try {
            response = sidecarClient.checkIp(ip);
        } catch (IOException e) {
            logger.error("Auth sidecar unreachable for ip={}: {}", ip, e.getMessage());
            event.setResult(PreLoginEvent.PreLoginComponentResult.denied(
                Component.text("Auth check failed — access denied")
            ));
            return;
        }

        boolean allowed = response.has("allowed") && response.get("allowed").getAsBoolean();
        if (!allowed) {
            String reason = response.has("reason") ? response.get("reason").getAsString() : "denied";
            logger.warn("Access denied username={} ip={} reason={}", username, ip, reason);
            event.setResult(PreLoginEvent.PreLoginComponentResult.denied(
                Component.text("Access denied: " + reason)
            ));
            return;
        }

        JsonObject identity = response.has("identity") ? response.getAsJsonObject("identity") : new JsonObject();
        pendingIdentities.put(username, identity);
        logger.info("Access allowed username={} ip={}", username, ip);
        event.setResult(PreLoginEvent.PreLoginComponentResult.forceOfflineMode());
    }

    @Subscribe
    public void onGameProfileRequest(GameProfileRequestEvent event) {
        String username = event.getUsername();
        JsonObject identity = pendingIdentities.get(username);
        String resolved = AuthSidecarClient.resolveUsername(username, identity);
        event.setGameProfile(GameProfile.forOfflinePlayer(resolved));
        logger.info("GameProfile resolved username={} resolved={}", username, resolved);
    }

    @Subscribe
    public void onDisconnect(DisconnectEvent event) {
        String username = event.getPlayer().getUsername();
        pendingIdentities.remove(username);
        logger.info("Disconnected username={}, identity removed", username);
    }
}
