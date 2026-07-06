package com.duo.app.service;

import com.duo.app.model.CollisionRequest;
import com.duo.app.model.CollisionResult;
import com.duo.app.model.PlanFootprint;
import com.duo.app.model.PlanPoint;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class CollisionService {

    private static final double EPSILON = 0.012;

    public List<CollisionResult> findCollisions(CollisionRequest request) {
        List<CollisionResult> collisions = new ArrayList<>();
        List<PlanFootprint> furniture = request.furniture() == null ? List.of() : request.furniture();
        List<PlanFootprint> walls = request.walls() == null ? List.of() : request.walls();

        for (PlanFootprint item : furniture) {
            for (PlanFootprint wall : walls) {
                if (intersects(item.points(), wall.points())) {
                    collisions.add(new CollisionResult(
                            item.id(),
                            item.label(),
                            wall.id(),
                            wall.label(),
                            "벡터 벽체"
                    ));
                }
            }
        }

        for (int i = 0; i < furniture.size(); i++) {
            for (int j = i + 1; j < furniture.size(); j++) {
                PlanFootprint first = furniture.get(i);
                PlanFootprint second = furniture.get(j);
                if (intersects(first.points(), second.points())) {
                    collisions.add(new CollisionResult(
                            first.id(),
                            first.label(),
                            second.id(),
                            second.label(),
                            "가구 간 충돌"
                    ));
                }
            }
        }

        return collisions;
    }

    private boolean intersects(List<PlanPoint> first, List<PlanPoint> second) {
        if (first == null || second == null || first.size() < 3 || second.size() < 3) {
            return false;
        }
        return !hasSeparatingAxis(first, second) && !hasSeparatingAxis(second, first);
    }

    private boolean hasSeparatingAxis(List<PlanPoint> first, List<PlanPoint> second) {
        for (int i = 0; i < first.size(); i++) {
            PlanPoint current = first.get(i);
            PlanPoint next = first.get((i + 1) % first.size());
            double edgeX = next.x() - current.x();
            double edgeZ = next.z() - current.z();
            Projection firstProjection = project(first, -edgeZ, edgeX);
            Projection secondProjection = project(second, -edgeZ, edgeX);
            if (firstProjection.max() <= secondProjection.min() + EPSILON
                    || secondProjection.max() <= firstProjection.min() + EPSILON) {
                return true;
            }
        }
        return false;
    }

    private Projection project(List<PlanPoint> points, double axisX, double axisZ) {
        double min = Double.POSITIVE_INFINITY;
        double max = Double.NEGATIVE_INFINITY;
        for (PlanPoint point : points) {
            double value = point.x() * axisX + point.z() * axisZ;
            min = Math.min(min, value);
            max = Math.max(max, value);
        }
        return new Projection(min, max);
    }

    private record Projection(double min, double max) {
    }
}
