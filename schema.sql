-- DuO Digital Twin Interior Web Simulator
-- MySQL DDL schema (reference architecture)

CREATE DATABASE IF NOT EXISTS duo_proptech
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE duo_proptech;

-- ---------------------------------------------------------------------------
-- apartments: master record for each residential unit / floor plan
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apartments (
    apartment_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    external_ref        VARCHAR(64)     NOT NULL COMMENT 'Public dataset or CRM identifier',
    building_name       VARCHAR(128)    NULL,
    unit_number         VARCHAR(32)     NULL,
    floor_level         SMALLINT        NULL,
    total_area_sqm      DECIMAL(10, 2)  NULL,
    room_count          TINYINT UNSIGNED NULL,
    blueprint_width_px  INT UNSIGNED    NULL,
    blueprint_height_px INT UNSIGNED    NULL,
    blueprint_uri       MEDIUMTEXT      NULL COMMENT 'Base64 data URI or storage URL',
    metadata_json       JSON            NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (apartment_id),
    UNIQUE KEY uq_apartments_external_ref (external_ref),
    KEY idx_apartments_building (building_name, unit_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- space_vectors: polygon / polyline geometry for rooms, walls, openings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS space_vectors (
    vector_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    apartment_id        BIGINT UNSIGNED NOT NULL,
    space_type          ENUM('room', 'wall', 'door', 'window', 'balcony', 'corridor', 'custom')
                        NOT NULL DEFAULT 'room',
    space_label         VARCHAR(64)     NULL COMMENT 'e.g. living_room, bedroom_1',
    vertex_index        INT UNSIGNED    NOT NULL DEFAULT 0,
    x_coord             DECIMAL(12, 4)  NOT NULL COMMENT 'Plan coordinate (mm or normalized)',
    y_coord             DECIMAL(12, 4)  NOT NULL,
    z_coord             DECIMAL(12, 4)  NOT NULL DEFAULT 0.0000,
    is_closed           TINYINT(1)      NOT NULL DEFAULT 1,
    properties_json     JSON            NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (vector_id),
    KEY idx_space_vectors_apartment (apartment_id, space_type),
    KEY idx_space_vectors_label (apartment_id, space_label, vertex_index),
    CONSTRAINT fk_space_vectors_apartment
        FOREIGN KEY (apartment_id) REFERENCES apartments (apartment_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- furniture_sku: catalog of placeable interior products
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS furniture_sku (
    sku_id              VARCHAR(32)     NOT NULL,
    product_name        VARCHAR(128)    NOT NULL,
    category            VARCHAR(64)     NOT NULL,
    width_mm            INT UNSIGNED    NOT NULL,
    depth_mm            INT UNSIGNED    NOT NULL,
    height_mm           INT UNSIGNED    NOT NULL,
    price_krw           DECIMAL(12, 2)  NOT NULL DEFAULT 0.00,
    model_path          VARCHAR(512)    NULL COMMENT 'Relative path under static/models',
    texture_path        VARCHAR(512)    NULL,
    color_hex           CHAR(7)         NULL,
    is_active           TINYINT(1)      NOT NULL DEFAULT 1,
    metadata_json       JSON            NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sku_id),
    KEY idx_furniture_category (category),
    KEY idx_furniture_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- finishing_materials: floor, wall, ceiling surface specifications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS finishing_materials (
    material_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    apartment_id        BIGINT UNSIGNED NULL COMMENT 'NULL = global catalog entry',
    surface_type        ENUM('floor', 'wall', 'ceiling', 'trim', 'countertop')
                        NOT NULL,
    material_name       VARCHAR(128)    NOT NULL,
    brand               VARCHAR(64)     NULL,
    sku_code            VARCHAR(64)     NULL,
    color_hex           CHAR(7)         NULL,
    texture_path        VARCHAR(512)    NULL,
    unit_price_sqm      DECIMAL(12, 2)  NULL,
    coverage_notes      VARCHAR(255)    NULL,
    properties_json     JSON            NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (material_id),
    KEY idx_finishing_apartment (apartment_id, surface_type),
    CONSTRAINT fk_finishing_apartment
        FOREIGN KEY (apartment_id) REFERENCES apartments (apartment_id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
