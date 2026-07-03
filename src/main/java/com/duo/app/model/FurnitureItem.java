package com.duo.app.model;

import com.fasterxml.jackson.annotation.JsonProperty;

public record FurnitureItem(
        @JsonProperty("sku_id") String skuId,
        @JsonProperty("product_name") String productName,
        String category,
        String price,
        String size,
        String color,
        @JsonProperty("model_path") String modelPath,
        @JsonProperty("image_url") String imageUrl,
        @JsonProperty("product_url") String productUrl,
        double width,
        double depth,
        double height
) {
}
