package com.duo.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.FileSystemUtils;
import org.springframework.web.multipart.MultipartFile;

@Service
public class FloorplanService {

    private static final String VECTORIZE_SCRIPT = "build_editable_floorplan.py";
    private static final String CACHE_VERSION = "floorplan-v1";
    private static final int MAX_CACHE_ENTRIES = 12;
    private static final int MAX_CONCURRENT_VECTORIZERS = 2;
    private static final long VECTORIZER_TIMEOUT_SECONDS = 180;

    private final ObjectMapper objectMapper;
    private final String pythonCommand;
    private final Semaphore vectorizerSlots = new Semaphore(MAX_CONCURRENT_VECTORIZERS, true);
    private final ConcurrentHashMap<String, CompletableFuture<JsonNode>> inFlight = new ConcurrentHashMap<>();
    private final Map<String, JsonNode> resultCache = new LinkedHashMap<>(16, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, JsonNode> eldest) {
            return size() > MAX_CACHE_ENTRIES;
        }
    };

    public FloorplanService(ObjectMapper objectMapper,
                            @Value("${floorplan.python.command:python3}") String pythonCommand) {
        this.objectMapper = objectMapper;
        this.pythonCommand = pythonCommand;
    }

    public JsonNode vectorize(MultipartFile file) throws IOException, InterruptedException {
        if (file.isEmpty()) {
            throw new IllegalArgumentException("빈 평면도 파일입니다.");
        }

        Path workDir = Path.of("").toAbsolutePath();
        Path script = workDir.resolve(VECTORIZE_SCRIPT);
        if (!Files.exists(script)) {
            throw new IllegalStateException("벡터화 스크립트를 찾지 못했습니다: " + script);
        }

        // 업로드 원본과 20MB 이상의 변환 결과는 요청별 임시 폴더에 저장된다.
        // 이전 구현은 이 폴더를 지우지 않아 요청할 때마다 디스크가 계속 늘었다.
        // 반환 JSON은 메모리로 읽은 뒤 finally에서 성공/실패 여부와 무관하게 정리한다.
        Path tempDir = Files.createTempDirectory("duo-floorplan-");
        try {
            Path input = tempDir.resolve(safeName(file.getOriginalFilename(), "floorplan.json"));
            Path output = tempDir.resolve("editable-floorplan.json");
            file.transferTo(input);

            String cacheKey = sha256(input);
            JsonNode cached = getCached(cacheKey);
            if (cached != null) {
                return decorateResult(cached, true);
            }

            CompletableFuture<JsonNode> ownFuture = new CompletableFuture<>();
            CompletableFuture<JsonNode> existingFuture = inFlight.putIfAbsent(cacheKey, ownFuture);
            if (existingFuture != null) {
                return decorateResult(awaitResult(existingFuture), true);
            }

            boolean acquired = false;
            try {
                vectorizerSlots.acquire();
                acquired = true;
                List<String> command = buildVectorizeCommand(script, input, output);
                runVectorizer(command, workDir);

                JsonNode result = objectMapper.readTree(output.toFile());
                putCached(cacheKey, result);
                ownFuture.complete(result.deepCopy());
                return decorateResult(result, false);
            } catch (IOException | InterruptedException | RuntimeException ex) {
                ownFuture.completeExceptionally(ex);
                throw ex;
            } finally {
                if (acquired) vectorizerSlots.release();
                inFlight.remove(cacheKey, ownFuture);
            }
        } finally {
            FileSystemUtils.deleteRecursively(tempDir);
        }
    }

    /** Python 스크립트의 위치·입출력·탐지 설정을 한곳에서 조립한다. */
    private List<String> buildVectorizeCommand(Path script, Path input, Path output) {
        List<String> command = new ArrayList<>();
        command.add(pythonCommand);
        command.add("-B"); // __pycache__를 만들지 않아 저장소와 임시 폴더를 깨끗하게 유지한다.
        command.add(script.toString());
        command.add(input.toString());
        command.add("-o");
        command.add(output.toString());
        return command;
    }

    /**
     * Python 로그를 먼저 끝까지 소비한 뒤 종료 코드를 확인한다.
     * stderr는 stdout으로 합쳐 오류가 발생했을 때 한 메시지에서 원인을 확인한다.
     */
    private void runVectorizer(List<String> command, Path workDir) throws IOException, InterruptedException {
        Process process;
        Path logFile = Files.createTempFile("duo-vectorizer-", ".log");
        try {
            process = new ProcessBuilder(command)
                    .directory(workDir.toFile())
                    .redirectErrorStream(true)
                    .redirectOutput(logFile.toFile())
                    .start();
        } catch (IOException ex) {
            Files.deleteIfExists(logFile);
            throw new IllegalStateException("Python 벡터화 프로세스를 시작하지 못했습니다. command=" + command, ex);
        }
        try {
            boolean finished = process.waitFor(VECTORIZER_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!finished) {
                process.destroy();
                if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly();
                throw new IllegalStateException("평면도 분석 제한 시간(" + VECTORIZER_TIMEOUT_SECONDS + "초)을 초과했습니다.");
            }
            int exitCode = process.exitValue();
            if (exitCode != 0) {
                String log = Files.readString(logFile);
                if (log.length() > 20_000) log = log.substring(log.length() - 20_000);
                throw new IllegalStateException("평면도 벡터화 실패(exit=" + exitCode + ", command=" + command + "): " + log);
            }
        } catch (InterruptedException ex) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw ex;
        } finally {
            Files.deleteIfExists(logFile);
        }
    }

    private String sha256(Path input) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(CACHE_VERSION.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try (InputStream stream = Files.newInputStream(input)) {
                byte[] buffer = new byte[64 * 1024];
                int count;
                while ((count = stream.read(buffer)) >= 0) {
                    if (count > 0) digest.update(buffer, 0, count);
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256을 사용할 수 없습니다.", ex);
        }
    }

    private synchronized JsonNode getCached(String key) {
        JsonNode result = resultCache.get(key);
        return result == null ? null : result.deepCopy();
    }

    private synchronized void putCached(String key, JsonNode value) {
        resultCache.put(key, value.deepCopy());
    }

    private JsonNode awaitResult(CompletableFuture<JsonNode> future) throws IOException, InterruptedException {
        try {
            return future.get().deepCopy();
        } catch (ExecutionException ex) {
            Throwable cause = ex.getCause();
            if (cause instanceof IOException ioException) throw ioException;
            if (cause instanceof InterruptedException interruptedException) throw interruptedException;
            if (cause instanceof RuntimeException runtimeException) throw runtimeException;
            throw new IllegalStateException("동일 평면도 분석 작업이 실패했습니다.", cause);
        }
    }

    private JsonNode decorateResult(JsonNode source, boolean cacheHit) {
        JsonNode result = source.deepCopy();
        if (result instanceof com.fasterxml.jackson.databind.node.ObjectNode objectNode) {
            objectNode.put("serverVectorizedAt", Instant.now().toString());
            objectNode.put("serverCacheHit", cacheHit);
        }
        return result;
    }

    private String safeName(String originalName, String fallback) {
        if (originalName == null || originalName.isBlank()) {
            return fallback;
        }
        String safe = originalName.replaceAll("[^a-zA-Z0-9._-]", "_");
        return safe.endsWith(".json") ? safe : fallback;
    }
}
