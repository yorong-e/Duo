#include <iostream>
#include <fstream>
#include <string>

// 가구의 사이즈를 받아 3D .obj 파일을 생성하는 함수
void generateFurnitureModel(const std::string& filename, float width, float depth, float height) {
    std::ofstream objFile(filename + ".obj");

    if (!objFile.is_open()) {
        std::cerr << "파일을 생성할 수 없습니다." << std::endl;
        return;
    }

    // 1. OBJ 파일 헤더 작성
    objFile << "# IKEA Furniture 3D Model\n";
    objFile << "# Generated from Crawled Data\n\n";

    // 가구 중심을 기준으로 8개의 꼭짓점(Vertex) 좌표 계산
    float w = width / 2.0f;
    float d = depth / 2.0f;
    float h = height; // 바닥에서부터 위로 쌓임

    // 2. 꼭짓점(v) 좌표 입력
    objFile << "v " << -w << " 0 " << -d << "\n"; // 1
    objFile << "v " <<  w << " 0 " << -d << "\n"; // 2
    objFile << "v " <<  w << " 0 " <<  d << "\n"; // 3
    objFile << "v " << -w << " 0 " <<  d << "\n"; // 4
    objFile << "v " << -w << " " << h << " " << -d << "\n"; // 5
    objFile << "v " <<  w << " " << h << " " << -d << "\n"; // 6
    objFile << "v " <<  w << " " << h << " " <<  d << "\n"; // 7
    objFile << "v " << -w << " " << h << " " <<  d << "\n\n"; // 8

    // 3. 면(f) 구성 (꼭짓점들을 연결하여 6개의 면을 만듦)
    objFile << "f 1 2 6 5\n"; // 뒤
    objFile << "f 2 3 7 6\n"; // 우
    objFile << "f 3 4 8 7\n"; // 앞
    objFile << "f 4 1 5 8\n"; // 좌
    objFile << "f 5 6 7 8\n"; // 위
    objFile << "f 4 3 2 1\n"; // 밑

    objFile.close();
    std::cout << filename << ".obj 3D 모델 생성 완료!" << std::endl;
}

int main() {
    // 예시: DB에서 소파 사이즈 [가로 180cm, 세로 90cm, 높이 75cm]를 긁어왔다고 가정 (미터 단위 변환)
    std::string furnitureName = "IKEA_Sofa_Example";
    float width = 1.8f;  
    float depth = 0.9f;  
    float height = 0.75f;

    generateFurnitureModel(furnitureName, width, depth, height);

    return 0;
}