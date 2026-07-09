package com.duo.app.model;

public record WallpaperItem(
        String productId,
        String productCode,
        String series,
        String name,
        Double widthMm,
        Double lengthM,
        String image,
        String imageUrl,
        String detailUrl,
        String price
) {
}
