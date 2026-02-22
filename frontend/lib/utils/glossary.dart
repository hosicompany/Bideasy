// 입찰 용어 사전 — 초보자 친화적 설명
//
// 화면 내 전문 용어 옆에 ⓘ 아이콘을 표시하고,
// 탭하면 BottomSheet로 쉬운 설명을 보여줌.

class GlossaryEntry {
  final String term;
  final String simple;
  final String detail;

  const GlossaryEntry({
    required this.term,
    required this.simple,
    required this.detail,
  });
}

const Map<String, GlossaryEntry> bidGlossary = {
  '기초금액': GlossaryEntry(
    term: '기초금액',
    simple: '입찰의 기준이 되는 금액이에요',
    detail: '발주처가 공고에 제시하는 공사 예상 비용이에요. '
        '이 금액을 기준으로 예정가격이 결정되고, 투찰가를 계산해요. '
        '설계금액에서 부가세를 뺀 금액과 비슷해요.',
  ),
  '예정가격': GlossaryEntry(
    term: '예정가격',
    simple: '실제 낙찰 기준이 되는 가격이에요',
    detail: '기초금액에서 ±2~3% 범위의 복수예비가격 중 추첨으로 결정돼요. '
        '이 가격의 87.745% 이상이어야 입찰에 참가할 수 있어요. '
        '개찰 직전까지 아무도 몰라요.',
  ),
  '사정률': GlossaryEntry(
    term: '사정률',
    simple: '예정가격 대비 낙찰가의 비율이에요',
    detail: '낙찰가 ÷ 예정가격 × 100으로 계산해요. '
        '보통 87~89% 사이에서 결정되고, '
        '이 비율에 가장 가까운 업체가 낙찰돼요.',
  ),
  '낙찰률': GlossaryEntry(
    term: '낙찰률',
    simple: '기초금액 대비 낙찰가의 비율이에요',
    detail: '낙찰가 ÷ 기초금액 × 100으로 계산해요. '
        '사정률과 비슷하지만 기준이 다르니 주의하세요.',
  ),
  '낙찰하한율': GlossaryEntry(
    term: '낙찰하한율',
    simple: '이 비율 아래로 투찰하면 무조건 탈락해요',
    detail: '예정가격의 87.745%가 기준이에요. '
        '이보다 낮은 가격을 쓰면 자동으로 실격 처리돼요. '
        'BidEasy에서 빨간색으로 경고해드려요.',
  ),
  '순공사원가': GlossaryEntry(
    term: '순공사원가',
    simple: '실제 공사에 드는 직접 비용이에요',
    detail: '재료비 + 노무비 + 경비를 합한 금액이에요. '
        '여기에 일반관리비, 이윤, 부가세를 더하면 기초금액이 돼요.',
  ),
  'A값': GlossaryEntry(
    term: 'A값',
    simple: '낙찰률이 적용되지 않는 고정 금액이에요',
    detail: '국민연금, 건강보험, 퇴직공제 등 법으로 정해진 비용이에요. '
        '투찰가 계산할 때 이 금액은 할인하지 않고 그대로 더해요.',
  ),
  '복수예비가격': GlossaryEntry(
    term: '복수예비가격',
    simple: '예정가격을 정하기 위한 후보 가격들이에요',
    detail: '기초금액의 ±2~3% 범위에서 15개가 생성되고, '
        '이 중 4개를 추첨하여 평균으로 예정가격을 결정해요.',
  ),
  '적격심사': GlossaryEntry(
    term: '적격심사',
    simple: '입찰 자격이 있는지 종합적으로 심사하는 거예요',
    detail: '가격 점수와 수행능력 점수를 합산하여 일정 기준 이상이면 낙찰돼요. '
        '단순히 가장 낮은 가격을 쓴다고 이기는 게 아니에요.',
  ),
  '블루오션': GlossaryEntry(
    term: '블루오션',
    simple: '경쟁이 적은 입찰 기회예요',
    detail: '참여업체가 5개사 이하로 예상되는 공고를 말해요. '
        '경쟁이 적을수록 낙찰 확률이 높아져요.',
  ),
  '투찰률': GlossaryEntry(
    term: '투찰률',
    simple: '기초금액 대비 내가 쓴 가격의 비율이에요',
    detail: '내 투찰가 ÷ 기초금액 × 100으로 계산해요. '
        '이 비율을 잘 조절하는 게 낙찰의 핵심이에요.',
  ),
};
