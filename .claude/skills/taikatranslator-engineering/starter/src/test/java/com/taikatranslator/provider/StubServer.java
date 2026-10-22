package com.taikatranslator.provider;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Local HTTP stub on 127.0.0.1 with a scripted handler. Lets provider clients
 * be tested for real HTTP behaviour (status codes, headers, bodies) with no
 * network and no credentials.
 */
final class StubServer implements AutoCloseable {

    record Recorded(String method, String path, Map<String, List<String>> headers, String body) { }

    record Reply(int status, String body, Map<String, String> headers) {
        static Reply json(int status, String body) {
            return new Reply(status, body, Map.of("Content-Type", "application/json"));
        }
    }

    @FunctionalInterface
    interface Handler {
        Reply handle(Recorded request, int callNumber) throws IOException;
    }

    private final HttpServer server;
    final List<Recorded> requests = new CopyOnWriteArrayList<>();

    StubServer(Handler handler) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> respond(ex, handler));
        server.start();
    }

    URI baseUri() {
        return URI.create("http://127.0.0.1:" + server.getAddress().getPort());
    }

    private void respond(HttpExchange ex, Handler handler) throws IOException {
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        Recorded rec = new Recorded(ex.getRequestMethod(), ex.getRequestURI().toString(), Map.copyOf(ex.getRequestHeaders()), body);
        requests.add(rec);
        Reply reply = handler.handle(rec, requests.size());
        reply.headers().forEach((k, v) -> ex.getResponseHeaders().add(k, v));
        byte[] bytes = reply.body() == null ? new byte[0] : reply.body().getBytes(StandardCharsets.UTF_8);
        ex.sendResponseHeaders(reply.status(), bytes.length == 0 ? -1 : bytes.length);
        if (bytes.length > 0) ex.getResponseBody().write(bytes);
        ex.close();
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
