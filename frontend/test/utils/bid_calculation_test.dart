import 'package:bideasy_app/models/notice.dart';
import 'package:bideasy_app/utils/bid_calculation.dart';
import 'package:flutter_test/flutter_test.dart';

Notice _notice({
  double basicPrice = 90000000,
  double? basisAmount = 100000000,
  String basisStatus = 'confirmed',
  String contractType = 'CONSTRUCTION',
  double? lowerLimitRate = 89.745,
  int? aValue,
  String? aValueSource,
  String? aValueApplicable,
}) {
  return Notice(
    bidNo: 'N-1',
    title: '테스트',
    content: '',
    basicPrice: basicPrice,
    basisAmount: basisAmount,
    basisStatus: basisStatus,
    contractType: contractType,
    lowerLimitRate: lowerLimitRate,
    aValue: aValue,
    aValueSource: aValueSource,
    aValueApplicable: aValueApplicable,
  );
}

void main() {
  test('does not substitute estimated price for missing confirmed basis', () {
    final notice = _notice(basisAmount: null, basisStatus: 'unconfirmed');

    expect(
      BidCalculationPolicy.abstainReason(notice),
      contains('확정 기초금액'),
    );
  });

  test('non-construction notice requires explicit lower-limit rate', () {
    final notice = _notice(
      contractType: 'SERVICE',
      lowerLimitRate: null,
    );

    expect(
      BidCalculationPolicy.abstainReason(notice),
      contains('공고에 명시된 낙찰하한율'),
    );
  });

  test('A-value formula and 10-won truncation match backend semantics', () {
    final bid = BidCalculationPolicy.calculateBidPrice(
      basisAmount: 100000003,
      adjustmentRate: -5,
      aValue: 1001,
    );
    final lower = BidCalculationPolicy.calculateLowerLimitPrice(
      basisAmount: 100000003,
      lowerLimitRate: 89.745,
      aValue: 1001,
    );

    expect(bid, 95000050);
    expect(lower, 89745100);
    expect(bid % 10, 0);
    expect(lower % 10, 0);
  });

  test('explicit A-value non-applicability disables A-value', () {
    final notice = _notice(aValue: 1000000, aValueApplicable: 'N');

    expect(BidCalculationPolicy.effectiveAValue(notice), 0);
    expect(BidCalculationPolicy.abstainReason(notice), isNull);
  });

  test('unknown A-value applicability abstains instead of assuming zero', () {
    final notice = _notice(aValue: 0, aValueApplicable: null);

    expect(BidCalculationPolicy.aValueStatus(notice), 'unknown');
    expect(BidCalculationPolicy.abstainReason(notice), contains('A값 적용 여부'));
  });

  test('positive sourced A-value is confirmed', () {
    final notice = _notice(
      aValue: 1000000,
      aValueSource: 'tier0',
      aValueApplicable: 'Y',
    );

    expect(BidCalculationPolicy.aValueStatus(notice), 'confirmed');
    expect(BidCalculationPolicy.abstainReason(notice), isNull);
  });
}
