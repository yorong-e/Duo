package com.duo.app.controller;

import com.duo.app.model.CollisionRequest;
import com.duo.app.model.CollisionResult;
import com.duo.app.service.CollisionService;
import com.duo.app.service.FloorplanService;
import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/floorplans")
public class FloorplanController {

    private final FloorplanService floorplanService;
    private final CollisionService collisionService;

    public FloorplanController(FloorplanService floorplanService, CollisionService collisionService) {
        this.floorplanService = floorplanService;
        this.collisionService = collisionService;
    }

    @PostMapping(path = "/vectorize", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public JsonNode vectorize(@RequestParam("file") MultipartFile file) throws IOException, InterruptedException {
        return floorplanService.vectorize(file);
    }

    @PostMapping("/collisions")
    public List<CollisionResult> collisions(@RequestBody CollisionRequest request) {
        return collisionService.findCollisions(request);
    }
}
