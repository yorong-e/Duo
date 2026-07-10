package com.duo.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.FileSystemUtils;
import org.springframework.web.multipart.MultipartFile;

@Service
public class FloorplanService {

    private static final String VECTORIZE_SCRIPT = "build_editable_floorplan.py";

    private final ObjectMapper objectMapper;
    private final String pythonCommand;
    private final String detectorModel;
    private final double detectorConfidence;

    public FloorplanService(ObjectMapper objectMapper,
                            @Value("${floorplan.python.command:python3}") String pythonCommand,
                            @Value("${floorplan.detector.model:weights/floorplan-fixtures.pt}") String detectorModel,
                            @Value("${floorplan.detector.confidence:0.4}") double detectorConfidence) {
        this.objectMapper = objectMapper;
        this.pythonCommand = pythonCommand;
        this.detectorModel = detectorModel;
        this.detectorConfidence = detectorConfidence;
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

            List<String> command = buildVectorizeCommand(script, input, output);
            runVectorizer(command, workDir);

            JsonNode result = objectMapper.readTree(output.toFile());
            if (result instanceof com.fasterxml.jackson.databind.node.ObjectNode objectNode) {
                objectNode.put("serverVectorizedAt", Instant.now().toString());
            }
            return result;
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
        if (detectorModel != null && !detectorModel.isBlank()) {
            command.add("--detector-model");
            command.add(detectorModel);
        }
        command.add("--detector-confidence");
        command.add(Double.toString(detectorConfidence));
        return command;
    }

    /**
     * Python 로그를 먼저 끝까지 소비한 뒤 종료 코드를 확인한다.
     * stderr는 stdout으로 합쳐 오류가 발생했을 때 한 메시지에서 원인을 확인한다.
     */
    private void runVectorizer(List<String> command, Path workDir) throws IOException, InterruptedException {
        Process process;
        try {
            process = new ProcessBuilder(command)
                    .directory(workDir.toFile())
                    .redirectErrorStream(true)
                    .start();
        } catch (IOException ex) {
            throw new IllegalStateException("Python 벡터화 프로세스를 시작하지 못했습니다. command=" + command, ex);
        }
        String log = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        int exitCode = process.waitFor();
        if (exitCode != 0) {
            throw new IllegalStateException("평면도 벡터화 실패(exit=" + exitCode + ", command=" + command + "): " + log);
        }
    }

    private String safeName(String originalName, String fallback) {
        if (originalName == null || originalName.isBlank()) {
            return fallback;
        }
        String safe = originalName.replaceAll("[^a-zA-Z0-9._-]", "_");
        return safe.endsWith(".json") ? safe : fallback;
    }
}
