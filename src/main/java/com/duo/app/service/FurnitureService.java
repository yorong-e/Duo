package com.duo.app.service;

import com.duo.app.model.FurnitureItem;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
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

    public List<FurnitureItem> findAll() {
        JdbcTemplate jdbcTemplate = jdbcTemplateProvider.getIfAvailable();
        if (jdbcTemplate == null) {
            return loadCsvCatalog();
        }

        try {
            return jdbcTemplate.query("""
                    SELECT id, category, image_url, name, size, price, product_url,
                           width_cm, depth_cm, height_cm
                    FROM furniture
                    """, (rs, rowNum) -> mapFurnitureRow(rs));
        } catch (DataAccessException ex) {
            log.warn("Could not load furniture from database; using CSV fallback catalog", ex);
            return loadCsvCatalog();
        }
    }

    private FurnitureItem mapFurnitureRow(ResultSet rs) throws SQLException {
        return new FurnitureItem(
                String.valueOf(rs.getObject("id")),
                rs.getString("name"),
                rs.getString("category"),
                rs.getString("price"),
                rs.getString("size"),
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
}
