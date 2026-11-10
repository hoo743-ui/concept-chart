# -*- coding: utf-8 -*-
"""정답 표시 (Claude, 2026-11-10, 관문 결과를 보기 전에 고정. 사용자 검토 전).

기준: 그 분야를 배워야 정확히 뜻을 아는 용어·이론·제도·사건·물질 = 공부할 개념.
아님: 많은 성인이 아는 일상어(금리·주식·혈압), 분야 이름(경제학·심리학), 사람·나라 이름, 낱말 조각(나당·구조론·활성부),
      단위(mg·dL), 형용사형(유전적·조작적), 답변을 쓴 LLM이 지어낸 낱말(근로기본법·스테이지플레이션·메타포린).
목록에 없는 낱말은 모두 '아님'이다.
"""
import json
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
POS_GENERAL = """
민법 유전자 단백질 면역계 미생물 변이 세균 실업률 억제제 인플레이션 진화 ACE Captopril Diuretics DNA enzyme GDP HDL LDL SGLT substrate defendant plaintiff AI
강제추행 개체 개체군 광합성 국채 근로계약 기준금리 기질 내성 냉전 노동법 당뇨 당뇨병 동맥경화 면역 미토콘드리아 민사소송 배당금 백신 병원체 복합체
산업혁명 산업화 세계대전 소멸시효 손해배상 스태그플레이션 신경병 유전자형 인슐린 임대인 임차인 임진왜란 자가면역 자연선택 재정정책 저항성 전세
중앙은행 지방산 케톤산증 콜레스테롤 통화량 통화정책 포도당 한정승인 항생제 항체 형법 형사소송 확정일자 환율 효소
생태계 반응물 채권
산화 NaCl 메탄 산화물 용액 이온 자산 부채 자본금 전자 CaO COOH KOH NaOH NOx Oxidation Reduction mol pH
감가상각 결정화 공급망 당기순이익 딸림화음 박자표 번아웃 변동성 부가가치 부가가치세 분위수 분자량 산성 산화환원 석영 석회암 손익계산서
수산화_나트륨 수산화_이온 수산화_칼륨 수소화물 아세트산 애착 엘니뇨 염기 염기성 영업이익 온실가스 온실효과 우울증 원자 유동성 음계 자전축
장조 단조 재무상태표 적외선 전도성 조건형성 조석 주주자본 중앙값 지각 질량 촉매 클로라이드 텐션 편향 평균율 표준편차 현금흐름표 화성학 환원 황동 황산 지질
""".split()


# 새 분야 세트 (data/eval/fresh, 물리학·천문학·철학·언어학·환경과학). Claude 표시 2026-11-10, 관문 결과를 보기 전에 고정. 사용자 검토 전.
# 같은 기준. 더해서: 화학식·영어 구절에서 잘린 조각(CO←CO₂, NO←NOₓ, PM←PM2.5, Fixation)은 아님, 큰 학문 이름(물리학·천문학)은 아님·세부 분야(열역학·통사론)는 개념.
FRESH_POS = """
입자 중력 생태계 연소 운동량 중력파 질량 천체 초신성 파동 파장 AQI Azotobacter Denitrification Nitrification Nitrobacter Nitrosomonas
Pseudomonas Rhizobium morpheme phoneme 공리주의 관성 광자 광전현상 교착어 궤도 귀납 연역 메탄 면역계 명제 미생물 박테리아 부영양화
블랙홀 산성 산성비 산성화 산화 서식지 세포 양자 양자역학 엔트로피 열역학 엽록체 온난화 온실가스 유기물 은하 음소 의무론 이데아 이데아론
인공지능 자연어_처리 적색편이 적색이동 전류 전압 전위 전하 전자 전자기장 전자기파 주파수 진화 질산염 아질산염 질소_고정 질소산화물
통사론 플랑크_상수 핵융합 형태소 형태학 환원 회로 단백질 알고리즘
""".split()


def main():
    fresh = "--set=fresh" in sys.argv
    d = ROOT / "data" / "eval" / ("fresh" if fresh else "general")
    POS = FRESH_POS if fresh else POS_GENERAL
    words = [x["form"] for x in json.loads((d / "words.json").read_text(encoding="utf-8"))]
    pos = {w.replace("_", " ") for w in POS}
    missing = sorted(pos - set(words))
    assert not missing, f"낱말 목록에 없는 정답: {missing}"
    gold = {w: w in pos for w in words}
    (d / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=0), encoding="utf-8")
    print("낱말", len(gold), "공부할 개념", sum(gold.values()))


if __name__ == "__main__":
    main()
