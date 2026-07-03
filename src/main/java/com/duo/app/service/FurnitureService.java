package com.duo.app.service;

import com.duo.app.model.FurnitureItem;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Locale;
import java.util.List;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.io.ClassPathResource;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class FurnitureService {

    private static final Logger log = LoggerFactory.getLogger(FurnitureService.class);

    private final ObjectProvider<JdbcTemplate> jdbcTemplateProvider;

    public FurnitureService(ObjectProvider<JdbcTemplate> jdbcTemplateProvider) {
        this.jdbcTemplateProvider = jdbcTemplateProvider;
    }

    public List<FurnitureItem> findAll(String color) {
        List<FurnitureItem> items = loadFurniture();
        if (color == null || color.isBlank() || "all".equalsIgnoreCase(color)) {
            return items;
        }

        String normalized = normalizeColor(color);
        return items.stream()
                .filter(item -> normalized.equals(normalizeColor(item.color())))
                .toList();
    }

    private List<FurnitureItem> loadFurniture() {
        JdbcTemplate jdbcTemplate = jdbcTemplateProvider.getIfAvailable();
        if (jdbcTemplate == null) {
            return loadCsvCatalog();
        }

        try {
            return jdbcTemplate.query("""
                    SELECT id, category, image_url, name, size, price, product_url,
                           width_cm, depth_cm, height_cm, color, model_path
                    FROM furniture
                    """, (rs, rowNum) -> mapFurnitureRow(rs));
        } catch (DataAccessException ex) {
            log.warn("Could not load model_path from database; trying color-only furniture catalog", ex);
            try {
                return jdbcTemplate.query("""
                        SELECT id, category, image_url, name, size, price, product_url,
                               width_cm, depth_cm, height_cm, color, NULL AS model_path
                        FROM furniture
                        """, (rs, rowNum) -> mapFurnitureRow(rs));
            } catch (DataAccessException colorOnlyEx) {
                log.warn("Could not load furniture from database; using CSV fallback catalog", colorOnlyEx);
                return loadCsvCatalog();
            }
        }
    }

    private FurnitureItem mapFurnitureRow(ResultSet rs) throws SQLException {
        return new FurnitureItem(
                String.valueOf(rs.getObject("id")),
                rs.getString("name"),
                rs.getString("category"),
                rs.getString("price"),
                rs.getString("size"),
                normalizeColor(rs.getString("color")),
                normalizeModelPath(rs.getString("model_path"), rs.getString("category"), rs.getString("color")),
                rs.getString("image_url"),
                rs.getString("product_url"),
                rs.getDouble("width_cm"),
                rs.getDouble("depth_cm"),
                rs.getDouble("height_cm")
        );
    }

    private List<FurnitureItem> loadCsvCatalog() {
        ClassPathResource resource = new ClassPathResource("furniture.csv");

        try (Reader reader = new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8);
             CSVParser parser = CSVFormat.DEFAULT.builder()
                     .setHeader()
                     .setSkipHeaderRecord(true)
                     .get()
                     .parse(reader)) {
            return parser.stream()
                    .map(this::mapFurnitureCsvRecord)
                    .toList();
        } catch (IOException ex) {
            throw new IllegalStateException("Could not load classpath furniture.csv fallback catalog", ex);
        }
    }

    private FurnitureItem mapFurnitureCsvRecord(CSVRecord record) {
        return new FurnitureItem(
                "csv-" + record.getRecordNumber(),
                record.get("이름"),
                record.get("카테고리"),
                record.get("가격"),
                record.get("사이즈"),
                inferColor(record),
                inferModelPath(record),
                record.get("이미지"),
                record.get("URL"),
                parseDouble(record.get("폭(cm)")),
                parseDouble(record.get("깊이(cm)")),
                parseDouble(record.get("높이(cm)"))
        );
    }

    private double parseDouble(String value) {
        if (value == null || value.isBlank()) {
            return 0.0;
        }
        return Double.parseDouble(value.trim());
    }

    private String inferColor(CSVRecord record) {
        String text = (record.get("이름") + " " + record.get("사이즈") + " " + record.get("이미지") + " " + record.get("URL"))
                .toLowerCase(Locale.ROOT);
        if (text.contains("black") || text.contains("dark")) {
            return "black";
        }
        if (text.contains("grey") || text.contains("gray")) {
            return "gray";
        }
        if (text.contains("brown") || text.contains("rust") || text.contains("golden")) {
            return "brown";
        }
        if (text.contains("blue")) {
            return "blue";
        }
        if (text.contains("white") || text.contains("beige") || text.contains("natural")) {
            return "white";
        }
        return "gray";
    }

    private String inferModelPath(CSVRecord record) {
        return normalizeModelPath(null, record.get("카테고리"), inferColor(record));
    }

    private String normalizeModelPath(String modelPath, String category, String color) {
        if (modelPath != null && !modelPath.isBlank()) {
            return modelPath.startsWith("/") ? modelPath : "/" + modelPath;
        }

        String normalizedColor = normalizeColor(color);
        String normalizedCategory = category == null ? "" : category.toLowerCase(Locale.ROOT);

        if (normalizedCategory.contains("bed") || normalizedCategory.contains("침대")) {
            String size = "black".equals(normalizedColor) || "white".equals(normalizedColor) ? "single" : "queen";
            return "/static/models/bed/" + size + "_" + normalizedColor + "_bed.glb";
        }

        if ("blue".equals(normalizedColor)) {
            return "/static/models/curve_sofa/blue_curve_sofa.glb";
        }

        return "/static/models/sofa/" + normalizedColor + "_sofa.glb";
    }

    private String normalizeColor(String color) {
        if (color == null || color.isBlank()) {
            return "gray";
        }

        String value = color.toLowerCase(Locale.ROOT).trim();
        return switch (value) {
            case "grey" -> "gray";
            case "dark grey", "dark gray" -> "black";
            case "off-white", "beige", "natural", "cream" -> "white";
            default -> value;
        };
    }
}
