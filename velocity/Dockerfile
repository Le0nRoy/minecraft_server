FROM gradle:8.10-jdk21 AS build
WORKDIR /build
COPY plugin/ .
RUN gradle shadowJar --no-daemon

FROM itzg/mc-proxy:java21
COPY --from=build /build/build/libs/mc-auth-bridge.jar /plugins/mc-auth-bridge.jar
COPY velocity.toml /config/velocity.toml
COPY forwarding.secret /config/forwarding.secret
