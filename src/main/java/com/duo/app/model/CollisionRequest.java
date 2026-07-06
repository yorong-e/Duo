package com.duo.app.model;

import java.util.List;

public record CollisionRequest(
        List<PlanFootprint> furniture,
        List<PlanFootprint> walls
) {
}
