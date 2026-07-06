package com.duo.app.model;

import java.util.List;

public record PlanFootprint(
        String id,
        String type,
        String label,
        List<PlanPoint> points
) {
}
