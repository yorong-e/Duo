package com.duo.app.controller;

import com.duo.app.model.WallpaperItem;
import com.duo.app.service.WallpaperService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/wallpapers")
public class WallpaperController {

    private final WallpaperService wallpaperService;

    public WallpaperController(WallpaperService wallpaperService) {
        this.wallpaperService = wallpaperService;
    }

    @GetMapping
    public List<WallpaperItem> listWallpapers() {
        return wallpaperService.findAll();
    }
}
