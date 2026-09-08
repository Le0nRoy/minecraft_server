package dev.le0nroy.mcauthbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

class AuthSidecarClient {

    private static final int HTTP_OK_MIN = 200;
    private static final int HTTP_OK_MAX = 299;
    private static final int HTTP_FORBIDDEN = 403;

    private final String baseUrl;
    private final int timeoutMs;

    AuthSidecarClient(String baseUrl, int timeoutMs) {
        this.baseUrl = baseUrl;
        this.timeoutMs = timeoutMs;
    }

    JsonObject checkIp(String ip) throws IOException {
        URL url = new URL(baseUrl + "/auth?ip=" + ip);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(timeoutMs);
        conn.setReadTimeout(timeoutMs);
        conn.setRequestMethod("GET");

        int responseCode = conn.getResponseCode();
        InputStream stream = (responseCode >= HTTP_OK_MIN && responseCode <= HTTP_OK_MAX)
            ? conn.getInputStream()
            : conn.getErrorStream();

        if (stream == null) {
            throw new IOException("No response body from auth sidecar, code=" + responseCode);
        }

        try (InputStreamReader reader = new InputStreamReader(stream, StandardCharsets.UTF_8)) {
            JsonObject parsed = JsonParser.parseReader(reader).getAsJsonObject();
            if (responseCode == HTTP_FORBIDDEN) {
                return parsed;
            }
            if (responseCode < HTTP_OK_MIN || responseCode > HTTP_OK_MAX) {
                throw new IOException("Auth sidecar returned unexpected status=" + responseCode);
            }
            return parsed;
        }
    }

    static String resolveUsername(String loginUsername, JsonObject identity) {
        if (identity == null) {
            return loginUsername;
        }
        if (identity.has("basename")) {
            return identity.get("basename").getAsString();
        }
        return loginUsername;
    }
}
