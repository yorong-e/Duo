package com.duo.app.service;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;

class FloorplanServiceTest {

    @Test
    void rejectsSavedLayoutBeforeStartingVectorizer() {
        FloorplanService service = new FloorplanService(new ObjectMapper(), "missing-python-command");
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "saved-layout.duo.json",
                "application/json",
                "{\"schema\":\"duo-layout\",\"version\":3,\"floorPlan\":{}}"
                        .getBytes(StandardCharsets.UTF_8));

        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> service.vectorize(file));

        assertTrue(error.getMessage().contains("저장된 배치 파일"));
    }
}
