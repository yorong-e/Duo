# DuO - Spring Boot Digital Twin Interior Simulator

DuO is now structured as a standard Spring Boot application. It serves the existing Three.js interior planning UI and exposes the furniture catalog API from the same application.

## Run

```bash
./mvnw spring-boot:run
```

Open:

```text
http://localhost:8080
```

## Verify

```bash
./mvnw test
curl http://localhost:8080/api/furniture
```

## Architecture

```text
Browser (Three.js)
    |
Spring Boot MVC static resources
    |
REST API (/api/furniture)
    |
MySQL when configured, otherwise bundled furniture.csv fallback
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
│   │   │   ├── config/DatabaseConfig.java
│   │   │   ├── controller/FurnitureController.java
│   │   │   ├── model/FurnitureItem.java
│   │   │   └── service/FurnitureService.java
│   │   └── resources/
│   │       ├── application.properties
│   │       ├── furniture.csv
│   │       ├── db/schema.sql
│   │       └── static/
│   │           ├── index.html
│   │           └── static/
│   │               ├── css/
│   │               ├── js/
│   │               ├── floorplan.json
│   │               └── models/
│   └── test/java/com/duo/app/DuoApplicationTests.java
├── core/
└── schema.sql
```

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Main 3D simulator UI |
| `GET` | `/api/furniture` | Furniture catalog JSON consumed by `main.js` |
| `GET` | `/actuator/health` | Spring Boot health endpoint |

## Database Configuration

The app starts without MySQL and serves `src/main/resources/furniture.csv`.

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

Reference DDL remains available at `schema.sql` and `src/main/resources/db/schema.sql`.

## Legacy Files

The previous Flask files (`app.py`, `requirements.txt`, `templates/`, and root `static/`) are left in place for reference, but the plug-and-play application entrypoint is now Spring Boot via `./mvnw spring-boot:run`.
