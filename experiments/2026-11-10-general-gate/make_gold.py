# -*- coding: utf-8 -*-
"""정답 표시 (Claude, 2026-11-10, 관문 결과를 보기 전에 고정. 사용자 검토 전).

기준: 그 분야를 배워야 정확히 뜻을 아는 용어·이론·제도·사건·물질 = 공부할 개념.
아님: 많은 성인이 아는 일상어(금리·주식·혈압), 분야 이름(경제학·심리학), 사람·나라 이름, 낱말 조각(나당·구조론·활성부),
      단위(mg·dL), 형용사형(유전적·조작적), 답변을 쓴 LLM이 지어낸 낱말(근로기본법·스테이지플레이션·메타포린).
목록에 없는 낱말은 모두 '아님'이다.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
POS = """
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


def main():
    d = ROOT / "data" / "eval" / "general"
    words = [x["form"] for x in json.loads((d / "words.json").read_text(encoding="utf-8"))]
    pos = {w.replace("_", " ") for w in POS}
    missing = sorted(pos - set(words))
    assert not missing, f"낱말 목록에 없는 정답: {missing}"
    gold = {w: w in pos for w in words}
    (d / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=0), encoding="utf-8")
    print("낱말", len(gold), "공부할 개념", sum(gold.values()))


if __name__ == "__main__":
    main()
