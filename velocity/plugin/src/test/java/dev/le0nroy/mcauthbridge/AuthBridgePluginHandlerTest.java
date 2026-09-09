package dev.le0nroy.mcauthbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpServer;
import com.velocitypowered.api.event.EventManager;
import com.velocitypowered.api.event.connection.DisconnectEvent;
import com.velocitypowered.api.event.connection.PreLoginEvent;
import com.velocitypowered.api.event.player.GameProfileRequestEvent;
import com.velocitypowered.api.proxy.Player;
import com.velocitypowered.api.proxy.ProxyServer;
import com.velocitypowered.api.util.GameProfile;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.Logger;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthBridgePluginHandlerTest {

    @Mock private ProxyServer mockProxy;
    @Mock private EventManager mockEventManager;
    @Mock private Logger mockLogger;
    @Mock private PreLoginEvent preLoginEvent;
    @Mock private GameProfileRequestEvent gameProfileEvent;
    @Mock private DisconnectEvent disconnectEvent;
    @Mock private Player mockPlayer;

    private HttpServer mockServer;
    private int mockPort;
    private AuthBridgePlugin plugin;

    @BeforeEach
    void setUp() throws Exception {
        mockServer = HttpServer.create(new InetSocketAddress(0), 0);
        mockServer.start();
        mockPort = mockServer.getAddress().getPort();

        when(mockProxy.getEventManager()).thenReturn(mockEventManager);
        AuthSidecarClient client = new AuthSidecarClient("http://localhost:" + mockPort, 5000);
        plugin = new AuthBridgePlugin(mockProxy, mockLogger, client);
    }

    @AfterEach
    void tearDown() {
        if (mockServer != null) {
            mockServer.stop(0);
        }
    }

    @Test
    void processPreLogin_allowed_storesIdentityAndSetsForceOfflineMode() throws Exception {
        String body = "{\"allowed\":true,\"identity\":{\"basename\":\"alice\"}}";
        mockServer.createContext("/auth", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        plugin.processPreLogin("alice", "100.64.0.1", preLoginEvent);

        assertTrue(plugin.pendingIdentities.containsKey("alice"));
        assertEquals("alice", plugin.pendingIdentities.get("alice").get("basename").getAsString());
        ArgumentCaptor<PreLoginEvent.PreLoginComponentResult> captor =
            ArgumentCaptor.forClass(PreLoginEvent.PreLoginComponentResult.class);
        verify(preLoginEvent).setResult(captor.capture());
        assertTrue(captor.getValue().isAllowed());
    }

    @Test
    void processPreLogin_denied_doesNotStoreIdentityAndSetsDenied() throws Exception {
        String body = "{\"allowed\":false,\"reason\":\"not in tailscale\"}";
        mockServer.createContext("/auth", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        plugin.processPreLogin("alice", "1.2.3.4", preLoginEvent);

        assertFalse(plugin.pendingIdentities.containsKey("alice"));
        ArgumentCaptor<PreLoginEvent.PreLoginComponentResult> captor =
            ArgumentCaptor.forClass(PreLoginEvent.PreLoginComponentResult.class);
        verify(preLoginEvent).setResult(captor.capture());
        assertFalse(captor.getValue().isAllowed());
    }

    @Test
    void processPreLogin_sidecarDown_deniesFailClosed() {
        AuthSidecarClient badClient = new AuthSidecarClient("http://localhost:1", 100);
        AuthBridgePlugin pluginWithBadClient = new AuthBridgePlugin(mockProxy, mockLogger, badClient);

        pluginWithBadClient.processPreLogin("alice", "100.64.0.1", preLoginEvent);

        assertFalse(pluginWithBadClient.pendingIdentities.containsKey("alice"));
        ArgumentCaptor<PreLoginEvent.PreLoginComponentResult> captor =
            ArgumentCaptor.forClass(PreLoginEvent.PreLoginComponentResult.class);
        verify(preLoginEvent).setResult(captor.capture());
        assertFalse(captor.getValue().isAllowed());
    }

    @Test
    void onGameProfileRequest_withStoredIdentity_usesBasename() {
        plugin.pendingIdentities.put("alice",
            JsonParser.parseString("{\"basename\":\"real-alice\"}").getAsJsonObject());
        when(gameProfileEvent.getUsername()).thenReturn("alice");

        plugin.onGameProfileRequest(gameProfileEvent);

        ArgumentCaptor<GameProfile> captor = ArgumentCaptor.forClass(GameProfile.class);
        verify(gameProfileEvent).setGameProfile(captor.capture());
        assertEquals("real-alice", captor.getValue().getName());
    }

    @Test
    void onGameProfileRequest_noStoredIdentity_usesLoginUsername() {
        when(gameProfileEvent.getUsername()).thenReturn("alice");

        plugin.onGameProfileRequest(gameProfileEvent);

        ArgumentCaptor<GameProfile> captor = ArgumentCaptor.forClass(GameProfile.class);
        verify(gameProfileEvent).setGameProfile(captor.capture());
        assertEquals("alice", captor.getValue().getName());
    }

    @Test
    void onDisconnect_removesIdentityFromPendingMap() {
        plugin.pendingIdentities.put("alice", new JsonObject());
        when(disconnectEvent.getPlayer()).thenReturn(mockPlayer);
        when(mockPlayer.getUsername()).thenReturn("alice");

        plugin.onDisconnect(disconnectEvent);

        assertFalse(plugin.pendingIdentities.containsKey("alice"));
    }
}
