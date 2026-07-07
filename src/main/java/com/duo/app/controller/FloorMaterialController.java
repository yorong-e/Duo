package com.duo.app.controller;

import com.duo.app.model.FloorMaterialItem;
import com.duo.app.service.FloorMaterialService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/floors")
public class FloorMaterialController {

    private final FloorMaterialService floorMaterialService;

    public FloorMaterialController(FloorMaterialService floorMaterialService) {
        this.floorMaterialService = floorMaterialService;
    }

    @GetMapping
    public List<FloorMaterialItem> listFloors() {
        return floorMaterialService.findAll();
    }
}
