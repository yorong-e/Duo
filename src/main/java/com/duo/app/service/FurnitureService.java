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
            return loadFallbackCatalog();
        }

        List<FurnitureItem> furnitureItems = loadFurnitureTable(jdbcTemplate);
        if (!furnitureItems.isEmpty()) {
            return furnitureItems;
        }

        try {
            List<FurnitureItem> items = jdbcTemplate.query("""
                    SELECT sku_id, product_name, category, width_mm, depth_mm, height_mm,
                           price_krw, model_path, color_hex
                    FROM furniture_sku
                    WHERE is_active = 1
                    """, (rs, rowNum) -> mapFurnitureSkuRow(rs));
            if (!items.isEmpty()) {
                return items;
            }
            log.warn("furniture_sku table returned no active rows; using fallback catalog");
            return loadFallbackCatalog();
        } catch (DataAccessException ex) {
            log.warn("Could not load furniture_sku from database; using fallback catalog: {}", ex.getMessage());
            return loadFallbackCatalog();
        }
    }

    private List<FurnitureItem> loadFurnitureTable(JdbcTemplate jdbcTemplate) {
        try {
            List<FurnitureItem> items = jdbcTemplate.query("""
                    SELECT category, image_url, name, size_description, color, price,
                           product_url, width_cm, depth_cm, height_cm
                    FROM furniture
                    ORDER BY category, name
                    """, (rs, rowNum) -> mapFurnitureRow(rs, rowNum));
            if (items.isEmpty()) {
                log.warn("furniture table returned no rows; trying furniture_sku");
            }
            return items;
        } catch (DataAccessException ex) {
            log.warn("Could not load furniture table; trying furniture_sku: {}", ex.getMessage());
            return List.of();
        }
    }

    private FurnitureItem mapFurnitureSkuRow(ResultSet rs) throws SQLException {
        String skuId = rs.getString("sku_id");
        String productName = rs.getString("product_name");
        String category = rs.getString("category");
        String modelPath = rs.getString("model_path");
        String color = inferColor(productName + " " + category + " " + modelPath + " " + rs.getString("color_hex"));
        return new FurnitureItem(
                skuId,
                productName,
                category,
                formatPrice(rs.getString("price_krw")),
                "",
                color,
                normalizeModelPath(modelPath, category, color),
                "",
                "",
                rs.getDouble("width_mm") / 10.0,
                rs.getDouble("depth_mm") / 10.0,
                rs.getDouble("height_mm") / 10.0
        );
    }

    private FurnitureItem mapFurnitureRow(ResultSet rs, int rowNum) throws SQLException {
        String category = rs.getString("category");
        String color = normalizeColor(rs.getString("color"));
        return new FurnitureItem(
                "db-" + (rowNum + 1),
                rs.getString("name"),
                category,
                rs.getString("price"),
                rs.getString("size_description"),
                color,
                "",
                normalizeImageUrl(rs.getString("image_url")),
                rs.getString("product_url"),
                rs.getDouble("width_cm"),
                rs.getDouble("depth_cm"),
                rs.getDouble("height_cm")
        );
    }

    private List<FurnitureItem> loadCsvCatalog() {
        ClassPathResource resource = new ClassPathResource("furniture.csv");

        if (!resource.exists()) {
            log.warn("Classpath furniture.csv not found; using built-in fallback catalog");
            return defaultFurnitureCatalog();
        }

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
            log.warn("Could not load classpath furniture.csv fallback catalog; using built-in fallback catalog", ex);
            return defaultFurnitureCatalog();
        }
    }

    private List<FurnitureItem> loadFallbackCatalog() {
        List<FurnitureItem> csvItems = loadCsvCatalog();
        return csvItems.isEmpty() ? defaultFurnitureCatalog() : csvItems;
    }

    private List<FurnitureItem> defaultFurnitureCatalog() {
        return List.of(
                defaultItem("default-sofa-gray", "그레이 소파", "sofa", "790000", "3인", "gray",
                        "/static/models/sofa/gray_sofa.glb", 210, 90, 80),
                defaultItem("default-sofa-brown", "브라운 소파", "sofa", "820000", "3인", "brown",
                        "/static/models/sofa/brown_sofa.glb", 210, 90, 80),
                defaultItem("default-sofa-blue", "블루 커브 소파", "sofa", "890000", "3인", "blue",
                        "/static/models/curve_sofa/blue_curve_sofa.glb", 220, 95, 78),
                defaultItem("default-bed-white", "화이트 침대", "bed", "650000", "single", "white",
                        "/static/models/bed/single_white_bed.glb", 110, 210, 85),
                defaultItem("default-bed-black", "블랙 침대", "bed", "680000", "single", "black",
                        "/static/models/bed/single_black_bed.glb", 110, 210, 85)
        );
    }

    private FurnitureItem defaultItem(String id, String name, String category, String price, String size,
                                      String color, String modelPath, double width, double depth, double height) {
        return new FurnitureItem(
                id,
                name,
                category,
                price,
                size,
                color,
                modelPath,
                "",
                "",
                width,
                depth,
                height
        );
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
        return inferColor(text);
    }

    private String inferColor(String text) {
        text = text == null ? "" : text.toLowerCase(Locale.ROOT);
        if (text.contains("black") || text.contains("dark") || text.contains("블랙") || text.contains("검정")) {
            return "black";
        }
        if (text.contains("grey") || text.contains("gray") || text.contains("그레이") || text.contains("회색")) {
            return "gray";
        }
        if (text.contains("brown") || text.contains("rust") || text.contains("golden") || text.contains("브라운") || text.contains("갈색")) {
            return "brown";
        }
        if (text.contains("blue") || text.contains("블루") || text.contains("파랑")) {
            return "blue";
        }
        if (text.contains("white") || text.contains("beige") || text.contains("natural") || text.contains("화이트") || text.contains("베이지")) {
            return "white";
        }
        return "gray";
    }

    private String formatPrice(String value) {
        if (value == null || value.isBlank()) {
            return "0";
        }
        int dot = value.indexOf('.');
        return dot >= 0 ? value.substring(0, dot) : value;
    }

    private String inferModelPath(CSVRecord record) {
        return normalizeModelPath(null, record.get("카테고리"), inferColor(record));
    }

    private String normalizeModelPath(String modelPath, String category, String color) {
        if (modelPath != null && !modelPath.isBlank()) {
            if (modelPath.startsWith("http://") || modelPath.startsWith("https://")) {
                return modelPath;
            }
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

    private String normalizeImageUrl(String imageUrl) {
        if (imageUrl == null || imageUrl.isBlank()) {
            return "";
        }
        String trimmed = imageUrl.trim();
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://") || trimmed.startsWith("data:image")) {
            return trimmed;
        }
        return trimmed.startsWith("/") ? trimmed : "/" + trimmed;
    }

    private String normalizeColor(String color) {
        if (color == null || color.isBlank()) {
            return "gray";
        }

        String value = color.toLowerCase(Locale.ROOT).trim();
        return switch (value) {
            case "grey" -> "gray";
            case "dark grey", "dark gray" -> "black";
            case "off-white", "beige", "natural", "cream", "화이트", "베이지", "아이보리" -> "white";
            case "그레이", "회색" -> "gray";
            case "브라운", "갈색" -> "brown";
            case "블랙", "검정", "검은색" -> "black";
            case "블루", "파랑", "파란색" -> "blue";
            default -> value;
        };
    }
}
