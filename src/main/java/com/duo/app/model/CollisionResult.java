package com.duo.app.model;

public record CollisionResult(
        String subjectId,
        String subjectLabel,
        String obstacleId,
        String obstacleLabel,
        String reason
) {
}
