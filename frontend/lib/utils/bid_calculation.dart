import '../models/notice.dart';

/// Safety boundary for Flutter bid calculators.
///
/// The rate and basis are supplied by the backend notice context. This helper
/// only applies the backend calculator's documented A-value and 10-won
/// truncation semantics so both Flutter entry points render the same amount.
class BidCalculationPolicy {
  const BidCalculationPolicy._();

  static String? abstainReason(Notice notice) {
    final basis = notice.confirmedBasisAmount;
    if (basis == null) {
      return '확정 기초금액을 확인하지 못해 투찰가를 계산할 수 없어요.';
    }

    final lowerRate = notice.lowerLimitRate;
    if (lowerRate == null) {
      if (notice.isConstruction) {
        return '공고 기준 낙찰하한율을 확인하지 못해 투찰가를 계산할 수 없어요.';
      }
      return '공사가 아닌 공고는 공고에 명시된 낙찰하한율이 있어야 해요.';
    }
    if (!lowerRate.isFinite || lowerRate < 0 || lowerRate > 100) {
      return '공고의 낙찰하한율이 유효하지 않아 계산을 중단했어요.';
    }

    final aStatus = aValueStatus(notice);
    if (aStatus == 'unknown') {
      return 'A값 적용 여부 또는 확정 A값을 확인하지 못해 계산을 중단했어요.';
    }
    final aValue = effectiveAValue(notice);
    if (aValue < 0 || aValue >= basis) {
      return 'A값이 확정 기초금액 범위를 벗어나 계산을 중단했어요.';
    }
    return null;
  }

  static int effectiveAValue(Notice notice) {
    final applicability = (notice.aValueApplicable ?? '').trim().toLowerCase();
    if (const {'n', 'no', 'false', '미적용', '해당없음'}.contains(applicability)) {
      return 0;
    }
    return notice.aValue ?? 0;
  }

  static String aValueStatus(Notice notice) {
    final applicability = (notice.aValueApplicable ?? '').trim().toLowerCase();
    if (const {'n', 'no', 'false', '미적용', '해당없음'}.contains(applicability)) {
      return 'not_applicable';
    }
    if ((notice.aValue ?? 0) > 0 && (notice.aValueSource ?? '').trim().isNotEmpty) {
      return 'confirmed';
    }
    return 'unknown';
  }

  static int truncateTo10Won(double amount) {
    return (amount / 10).floor() * 10;
  }

  static int calculateBidPrice({
    required double basisAmount,
    required double adjustmentRate,
    int aValue = 0,
  }) {
    final variableAmount = basisAmount - aValue;
    final raw = (variableAmount * (1 + adjustmentRate / 100)) + aValue;
    return truncateTo10Won(raw);
  }

  static int calculateLowerLimitPrice({
    required double basisAmount,
    required double lowerLimitRate,
    int aValue = 0,
  }) {
    final variableAmount = basisAmount - aValue;
    final raw = (variableAmount * (lowerLimitRate / 100)) + aValue;
    return truncateTo10Won(raw);
  }
}
