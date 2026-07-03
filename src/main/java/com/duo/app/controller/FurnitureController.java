package com.duo.app.controller;

import com.duo.app.model.FurnitureItem;
import com.duo.app.service.FurnitureService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/furniture")
public class FurnitureController {

    private final FurnitureService furnitureService;

    public FurnitureController(FurnitureService furnitureService) {
        this.furnitureService = furnitureService;
    }

    @GetMapping
    public List<FurnitureItem> listFurniture(@RequestParam(required = false) String color) {
        return furnitureService.findAll(color);
    }
}
