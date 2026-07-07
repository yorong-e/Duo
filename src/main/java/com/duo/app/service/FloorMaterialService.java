package com.duo.app.service;

import com.duo.app.model.FloorMaterialItem;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class FloorMaterialService {

    private static final Logger log = LoggerFactory.getLogger(FloorMaterialService.class);
    private static final List<Path> FLOOR_IMAGE_DIRS = List.of(
            Path.of("src", "floorImage"),
            Path.of("src", "floorimage")
    );
    private static final List<String> IMAGE_EXTENSIONS = List.of(".jpg", ".jpeg", ".png", ".webp");

    private final ObjectProvider<JdbcTemplate> jdbcTemplateProvider;

    public FloorMaterialService(ObjectProvider<JdbcTemplate> jdbcTemplateProvider) {
        this.jdbcTemplateProvider = jdbcTemplateProvider;
    }

    public List<FloorMaterialItem> findAll() {
        JdbcTemplate jdbcTemplate = jdbcTemplateProvider.getIfAvailable();
        if (jdbcTemplate == null) {
            return List.of();
        }

        try {
            return jdbcTemplate.query("""
                    SELECT product_id, product_code, series, name, thickness_mm,
                           width_mm, length_m, image, detail_url, price
                    FROM `floor`
                    ORDER BY series, product_code
                    """, (rs, rowNum) -> mapFloorRow(rs));
        } catch (DataAccessException ex) {
            log.warn("Could not load floor table from database: {}", ex.getMessage());
            return List.of();
        }
    }

    private FloorMaterialItem mapFloorRow(ResultSet rs) throws SQLException {
        String productCode = rs.getString("product_code");
        String image = rs.getString("image");
        String imageUrl = resolveImageUrl(productCode, image);
        return new FloorMaterialItem(
                rs.getString("product_id"),
                productCode,
                rs.getString("series"),
                rs.getString("name"),
                readDouble(rs, "thickness_mm"),
                readDouble(rs, "width_mm"),
                readDouble(rs, "length_m"),
                image,
                imageUrl,
                rs.getString("detail_url"),
                rs.getString("price")
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
                return "/floorimage/" + normalized;
            }
            String fileName = Path.of(normalized).getFileName().toString();
            if (imageFileExists(fileName)) {
                return "/floorimage/" + fileName;
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
            return "/floorimage/" + code;
        }
        for (String ext : IMAGE_EXTENSIONS) {
            String fileName = code + ext;
            if (imageFileExists(fileName)) {
                return "/floorimage/" + fileName;
            }
            String lowerFileName = code.toLowerCase(Locale.ROOT) + ext;
            if (imageFileExists(lowerFileName)) {
                return "/floorimage/" + lowerFileName;
            }
        }
        return "";
    }

    private boolean imageFileExists(String fileName) {
        return FLOOR_IMAGE_DIRS.stream().anyMatch(dir -> Files.exists(dir.resolve(fileName)));
    }
}
