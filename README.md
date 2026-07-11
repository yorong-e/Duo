# DuO - Spring Boot Digital Twin Interior Simulator

DuO is structured as a Spring Boot application. It serves the Three.js interior planning UI, exposes furniture catalog APIs, and runs floorplan vectorization/collision services from the backend.

## Run

```bash
./mvnw spring-boot:run
```

Open:

```text
http://localhost:8081
```

## Verify

```bash
./mvnw test
curl http://localhost:8081/api/furniture
```

## Architecture

```text
Browser (Three.js)
    |
Spring Boot MVC static resources
    |
REST API (/api/furniture, /api/floorplans)
    |
Floorplan services + MySQL when configured, otherwise bundled furniture.csv fallback
```

## Project Structure

```text
DuO/
├── pom.xml
├── mvnw
├── mvnw.cmd
├── src/
│   ├── main/
│   │   ├── java/com/duo/app/
│   │   │   ├── DuoApplication.java
│   │   │   ├── config/
│   │   │   ├── controller/
│   │   │   │   ├── FurnitureController.java
│   │   │   │   └── FloorplanController.java
│   │   │   ├── model/
│   │   │   └── service/
│   │   │       ├── FurnitureService.java
│   │   │       ├── FloorplanService.java
│   │   │       └── CollisionService.java
│   │   └── resources/
│   │       ├── application.properties
│   │       ├── db/schema.sql
│   │       └── static/
│   │           ├── index.html
│   │           └── static/
│   │               ├── css/
│   │               ├── js/
│   │               └── models/
│   └── test/java/com/duo/app/DuoApplicationTests.java
├── build_editable_floorplan.py
├── extract_layers.py
├── extract_walls.py
├── floorplan_vectorizer.py
├── floorplan_object_detector.py
├── requirements-floorplan.txt
└── weights/
```

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Main 3D simulator UI |
| `GET` | `/api/furniture` | Furniture catalog JSON consumed by `main.js` |
| `POST` | `/api/floorplans/vectorize` | Upload a source floorplan JSON and receive reconstructed editable floors/walls |
| `POST` | `/api/floorplans/collisions` | Validate vector footprints against walls/furniture on the backend |
| `GET` | `/actuator/health` | Spring Boot health endpoint |

## Floor-plan Room Labels

On macOS, the vectorization endpoint uses Vision OCR to recognize text and
keeps only known room names such as `욕실`, `주방`, and `침실`. It returns
the recognized string and source coordinates in `room_labels[]`; furniture
lines, dimensions, and symbols are not rendered as labels. Large neutral-gray
filled regions are returned as `layers.non_residential_mask`, rendered gray,
and excluded from furniture placement.

Room segmentation uses only the extracted physical wall mask. Furniture,
floor patterns, and text no longer create virtual room boundaries. Short wall
gaps are regularized into solid wall runs, while door-sized openings remain
visible; door openings are closed only temporarily while calculating room
connectivity.

Gray-region filtering defaults to at least 1% of the full image with a 42%
bounding-box fill density. Tune it with
`FLOORPLAN_NON_RESIDENTIAL_MIN_AREA_RATIO` and
`FLOORPLAN_NON_RESIDENTIAL_MIN_DENSITY` when a drawing profile needs stricter
or looser filtering. For bounded spaces, at least 60% of the room must be gray;
this can be changed with `FLOORPLAN_NON_RESIDENTIAL_ROOM_GRAY_RATIO`.

Install the Python inference dependencies in the interpreter configured by
`floorplan.python.command`:

```bash
/opt/anaconda3/bin/python3 -m pip install -r requirements-floorplan.txt
```

## Database Configuration

The app starts without MySQL and serves the built-in furniture fallback catalog.

To use MySQL instead, provide Spring datasource environment variables before running:

```bash
export SPRING_DATASOURCE_URL='jdbc:mysql://localhost:3306/Duo?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Seoul'
export SPRING_DATASOURCE_USERNAME='root'
export SPRING_DATASOURCE_PASSWORD='your-password'
./mvnw spring-boot:run
```

The API expects a `furniture` table with these columns:

```text
id, category, image_url, name, size, price, product_url, width_cm, depth_cm, height_cm
```

Reference DDL remains available at `src/main/resources/db/schema.sql`.

## Removed Legacy Files

The old Flask entrypoint and duplicate root static assets were removed. The plug-and-play application entrypoint is Spring Boot via `./mvnw spring-boot:run`.
