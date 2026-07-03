from __future__ import annotations
import json
import os
from pathlib import Path
from flask import Flask, jsonify, render_template
import pymysql  # 💡 MySQL 연동을 위해 추가 (pip install pymysql)

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)

# 💡 MySQL DB 연결 함수 (데이터베이스 이름을 'Duo'로 반영)
def get_db_connection():
    return pymysql.connect(
        host="localhost",
        user="root",          # 본인의 MySQL 유저명
        password="q@2468435",  # 본인의 MySQL 비밀번호
        db="Duo",             # 🌟 'ikea_products'에서 'Duo'로 수정 완료!
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

# 💡 크롤링된 사이즈 문자열(예: "180x90x75 cm" 또는 "180 cm")을 mm 단위 숫자로 파싱하는 헬퍼 함수
def parse_size(size_str):
    # 기본값 설정 (파싱 실패 대비)
    width, depth, height = 1000, 800, 750 
    try:
        # 문자열에서 숫자만 추출하거나 'x' 단위로 쪼개는 로직ㅁ
        # 이케아 특성상 "가로x세로x높이" 혹은 "폭x깊이x높이" 구조가 많습니다.
        clean_str = size_str.replace("cm", "").replace("mm", "").strip()
        if "x" in clean_str:
            parts = [float(p.strip()) for p in clean_str.split("x")]
            if len(parts) >= 3:
                width, depth, height = parts[0] * 10, parts[1] * 10, parts[2] * 10 # cm -> mm 변환
            elif len(parts) == 2:
                width, depth = parts[0] * 10, parts[1] * 10
    except Exception as e:
        print(f"사이즈 파싱 에러: {e}")
    return width, depth, height

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/furniture", methods=["GET"])
def api_furniture():
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. 이제 'furniture' 테이블에 위 컬럼들이 정확히 있다고 가정하고 조회합니다.
            query = """
                SELECT id, category, image_url, name, size, price, product_url, width_cm, depth_cm, height_cm 
                FROM furniture
            """
            cursor.execute(query)
            rows = cursor.fetchall()
        conn.close()

        # 2. JSON 데이터 매핑 (main.js가 사용하는 키값과 일치시킵니다)
        furniture_list = []
        for row in rows:
            furniture_list.append({
                "sku_id": row["id"],
                "product_name": row["name"],
                "category": row["category"],
                "price": row["price"],
                "size": row["size"],
                # 💡 카탈로그에서 썸네일/상세링크를 보여주려면 프론트가 이 값을 필요로 함
                "image_url": row["image_url"],
                "product_url": row["product_url"],
                # CSV 데이터는 숫자 타입일 수도 있고 문자열일 수도 있어 float으로 형변환
                "width": float(row["width_cm"] or 0),
                "depth": float(row["depth_cm"] or 0),
                "height": float(row["height_cm"] or 0)
            })
            
        return jsonify(furniture_list)
        
    except Exception as e:
        print(f"❌ DB 조회 에러 발생: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)