package com.duo.app.service;

import com.duo.app.model.WallpaperItem;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class WallpaperService {

    private static final Logger log = LoggerFactory.getLogger(WallpaperService.class);
    private static final List<Path> WALLPAPER_IMAGE_DIRS = List.of(
            Path.of("src", "wallpaper_images"),
            Path.of("src", "wallpaperImages"),
            Path.of("src", "wallpaperimages")
    );
    private static final List<String> IMAGE_EXTENSIONS = List.of(".jpg", ".jpeg", ".png", ".webp");

    private final ObjectProvider<JdbcTemplate> jdbcTemplateProvider;

    public WallpaperService(ObjectProvider<JdbcTemplate> jdbcTemplateProvider) {
        this.jdbcTemplateProvider = jdbcTemplateProvider;
    }

    public List<WallpaperItem> findAll() {
        JdbcTemplate jdbcTemplate = jdbcTemplateProvider.getIfAvailable();
        if (jdbcTemplate != null) {
            try {
                List<WallpaperItem> items = jdbcTemplate.query("""
                        SELECT product_id, product_code, series, name,
                               width_mm, length_m, image, detail_url, price
                        FROM wallpaper
                        ORDER BY series, product_code
                        """, (rs, rowNum) -> mapWallpaperRow(rs));
                if (!items.isEmpty()) {
                    return items;
                }
            } catch (DataAccessException ex) {
                log.warn("Could not load wallpaper table from database: {}", ex.getMessage());
            }
        }
        return listLocalWallpapers();
    }

    private WallpaperItem mapWallpaperRow(ResultSet rs) throws SQLException {
        String productCode = rs.getString("product_code");
        String image = rs.getString("image");
        String imageUrl = resolveImageUrl(productCode, image);
        return new WallpaperItem(
                rs.getString("product_id"),
                productCode,
                rs.getString("series"),
                rs.getString("name"),
                readDouble(rs, "width_mm"),
                readDouble(rs, "length_m"),
                image,
                imageUrl,
                rs.getString("detail_url"),
                rs.getString("price")
        );
    }

    private List<WallpaperItem> listLocalWallpapers() {
        return WALLPAPER_IMAGE_DIRS.stream()
                .filter(Files::isDirectory)
                .findFirst()
                .map(this::readWallpaperDirectory)
                .orElseGet(List::of);
    }

    private List<WallpaperItem> readWallpaperDirectory(Path dir) {
        try (var stream = Files.list(dir)) {
            return stream
                    .filter(Files::isRegularFile)
                    .filter(path -> IMAGE_EXTENSIONS.stream().anyMatch(ext -> path.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(ext)))
                    .sorted(Comparator.comparing(path -> path.getFileName().toString()))
                    .map(this::mapLocalWallpaper)
                    .toList();
        } catch (IOException ex) {
            log.warn("Could not scan wallpaper images in {}: {}", dir, ex.getMessage());
            return List.of();
        }
    }

    private WallpaperItem mapLocalWallpaper(Path path) {
        String fileName = path.getFileName().toString();
        String productCode = stripExtension(fileName);
        return new WallpaperItem(
                productCode,
                productCode,
                "",
                productCode,
                null,
                null,
                fileName,
                "/wallpaperimage/" + fileName,
                "",
                ""
        );
    }

    private Double readDouble(ResultSet rs, String column) throws SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }

    private String resolveImageUrl(String productCode, String image) {
        String code = productCode == null ? "" : productCode.trim();
        String localProductImage = resolveLocalProductImage(code);
        if (!localProductImage.isBlank()) {
            return localProductImage;
        }

        String imageName = image == null ? "" : image.trim();
        if (!imageName.isBlank()) {
            String normalized = imageName.startsWith("/") ? imageName.substring(1) : imageName;
            if (imageFileExists(normalized)) {
                return "/wallpaperimage/" + normalized;
            }
            String fileName = Path.of(normalized).getFileName().toString();
            if (imageFileExists(fileName)) {
                return "/wallpaperimage/" + fileName;
            }
            if (imageName.startsWith("http://") || imageName.startsWith("https://")) {
                return imageName;
            }
        }

        return "";
    }

    private String resolveLocalProductImage(String code) {
        if (code.isBlank()) {
            return "";
        }
        if (imageFileExists(code)) {
            return "/wallpaperimage/" + code;
        }
        for (String ext : IMAGE_EXTENSIONS) {
            String fileName = code + ext;
            if (imageFileExists(fileName)) {
                return "/wallpaperimage/" + fileName;
            }
            String lowerFileName = code.toLowerCase(Locale.ROOT) + ext;
            if (imageFileExists(lowerFileName)) {
                return "/wallpaperimage/" + lowerFileName;
            }
        }
        return "";
    }

    private boolean imageFileExists(String fileName) {
        return WALLPAPER_IMAGE_DIRS.stream().anyMatch(dir -> Files.exists(dir.resolve(fileName)));
    }

    private String stripExtension(String fileName) {
        int dot = fileName.lastIndexOf('.');
        return dot > 0 ? fileName.substring(0, dot) : fileName;
    }
}
