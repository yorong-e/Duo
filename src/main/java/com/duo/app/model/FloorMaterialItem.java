package com.duo.app.model;

public record FloorMaterialItem(
        String productId,
        String productCode,
        String series,
        String name,
        Double thicknessMm,
        Double widthMm,
        Double lengthM,
        String image,
        String imageUrl,
        String detailUrl,
        String price
) {
}
