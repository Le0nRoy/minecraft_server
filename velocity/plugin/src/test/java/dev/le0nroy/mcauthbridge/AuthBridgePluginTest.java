package dev.le0nroy.mcauthbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;

class AuthBridgePluginTest {

    private HttpServer mockServer;
    private int mockPort;

    @BeforeEach
    void setUp() throws Exception {
        mockServer = HttpServer.create(new InetSocketAddress(0), 0);
        mockServer.start();
        mockPort = mockServer.getAddress().getPort();
    }

    @AfterEach
    void tearDown() {
        if (mockServer != null) {
            mockServer.stop(0);
        }
    }

    private AuthSidecarClient client(int timeoutMs) {
        return new AuthSidecarClient("http://localhost:" + mockPort, timeoutMs);
    }

    @Test
    void checkIp_200_allowed() throws Exception {
        String body = "{\"allowed\":true,\"reason\":\"tailscale\",\"identity\":{\"basename\":\"alice\"}}";
        mockServer.createContext("/auth", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        JsonObject result = client(5000).checkIp("100.64.0.1");

        assertTrue(result.get("allowed").getAsBoolean());
        assertEquals("tailscale", result.get("reason").getAsString());
        assertEquals("alice", result.getAsJsonObject("identity").get("basename").getAsString());
    }

    @Test
    void checkIp_403_denied() throws Exception {
        String body = "{\"allowed\":false,\"reason\":\"denied\",\"identity\":{}}";
        mockServer.createContext("/auth", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(403, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        JsonObject result = client(5000).checkIp("1.2.3.4");

        assertFalse(result.get("allowed").getAsBoolean());
        assertEquals("denied", result.get("reason").getAsString());
    }

    @Test
    void checkIp_timeout_throwsIOException() {
        mockServer.createContext("/auth", exchange -> {
            try {
                Thread.sleep(10_000);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        });

        assertThrows(IOException.class, () -> client(100).checkIp("100.64.0.1"));
    }

    @Test
    void checkIp_malformedJson_throwsException() {
        String body = "not-valid-json!!!";
        mockServer.createContext("/auth", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        assertThrows(Exception.class, () -> client(5000).checkIp("100.64.0.1"));
    }

    @Test
    void resolveUsername_withBasename_returnsBasename() {
        JsonObject identity = JsonParser.parseString("{\"basename\":\"alice\"}").getAsJsonObject();
        assertEquals("alice", AuthSidecarClient.resolveUsername("SomeLoginName", identity));
    }

    @Test
    void resolveUsername_withoutBasename_returnsLoginUsername() {
        JsonObject identity = JsonParser.parseString("{\"reachable\":true,\"mac\":\"aa:bb:cc\"}").getAsJsonObject();
        assertEquals("SomeLoginName", AuthSidecarClient.resolveUsername("SomeLoginName", identity));
    }

    @Test
    void resolveUsername_nullIdentity_returnsLoginUsername() {
        assertEquals("SomeLoginName", AuthSidecarClient.resolveUsername("SomeLoginName", null));
    }
}
