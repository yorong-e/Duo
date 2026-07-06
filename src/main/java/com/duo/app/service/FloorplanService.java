package com.duo.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

@Service
public class FloorplanService {

    private static final String VECTORIZE_SCRIPT = "build_editable_floorplan.py";

    private final ObjectMapper objectMapper;
    private final String pythonCommand;

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

        Path tempDir = Files.createTempDirectory("duo-floorplan-");
        Path input = tempDir.resolve(safeName(file.getOriginalFilename(), "floorplan.json"));
        Path output = tempDir.resolve("editable-floorplan.json");
        Path debugDir = tempDir.resolve("debug");

        file.transferTo(input);

        List<String> command = new ArrayList<>();
        command.add(pythonCommand);
        command.add("-B");
        command.add(script.toString());
        command.add(input.toString());
        command.add("-o");
        command.add(output.toString());
        command.add("--debug-dir");
        command.add(debugDir.toString());

        Process process;
        try {
            process = new ProcessBuilder(command)
                    .directory(workDir.toFile())
                    .redirectErrorStream(true)
                    .start();
        } catch (IOException ex) {
            throw new IllegalStateException("Python 벡터화 프로세스를 시작하지 못했습니다. command=" + command, ex);
        }
        String log = new String(process.getInputStream().readAllBytes());
        int exitCode = process.waitFor();
        if (exitCode != 0) {
            throw new IllegalStateException("평면도 벡터화 실패(exit=" + exitCode + ", command=" + command + "): " + log);
        }

        JsonNode result = objectMapper.readTree(output.toFile());
        if (result instanceof com.fasterxml.jackson.databind.node.ObjectNode objectNode) {
            objectNode.put("serverVectorizedAt", Instant.now().toString());
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
