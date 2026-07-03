/**
 * DuO Core Calculation Engine
 * 공간 충돌 및 레이아웃 검증을 위한 공유 라이브러리(Shared Library).
 */

// 파이썬(ctypes)에서 이 C++ 함수를 이름 그대로 인식하고 호출할 수 있도록 
// C 언어 형태로 컴파일러에게 링킹을 지시합니다. (이름 변형 방지)
extern "C" {

/**
 * 가구의 배치 영 개폐역(발자국)과 문의 반경(클리어런스) 사이의 충돌을 검사하는 스텁(Stub) 함수입니다.
 *
 * @param f_x  가구의 중심 X 좌표 (도면 단위)
 * @param f_y  가구의 중심 Y 좌표 (도면 단위)
 * @param f_w  가구의 가로 길이 (Width)
 * @param f_d  가구의 세로 깊이 (Depth)
 * @param d_x  문의 중심 X 좌표
 * @param d_y  문의 중심 Y 좌표
 * @param d_r  문이 열리기 위해 필요한 여유 반경 (Clearance Radius)
 * @return 충돌이 감지되면 true, 겹치지 않으면 false를 반환 (현재는 무조건 false)
 */
bool check_collision(
    float f_x, float f_y, float f_w, float f_d,
    float d_x, float d_y, float d_r)
{
    // [컴파일러 경고 방지 구문]
    // 현재는 변수들을 가지고 실제 계산을 하지 않기 때문에, 
    // 컴파일러가 "왜 변수를 만들어놓고 쓰지 않느냐?"라며 에러나 경고를 내는 것을 방지하기 위해 
    // 명시적으로 빈 캐스팅((void)) 처리를 해둔 것입니다.
    (void)f_x;
    (void)f_y;
    (void)f_w;
    (void)f_d;
    (void)d_x;
    (void)d_y;
    (void)d_r;

    // 현재는 단순 연결 테스트 단계이므로 
    // 아무런 가구도 문과 충돌하지 않은 상태(false)를 무조건 반환합니다.
    return false;
}

} // extern "C"