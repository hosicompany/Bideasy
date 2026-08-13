import 'package:bideasy_app/models/notice.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses additive calculation context fields without changing estimate',
      () {
    final notice = Notice.fromJson({
      'bid_no': 'N-1',
      'title': '테스트 공사',
      'content': '',
      'basic_price': 90000000,
      'basis_amount': '100000000',
      'basis_status': 'confirmed',
      'basis_amount_at': '2026-08-13T09:00:00+09:00',
      'contract_type': 'CONSTRUCTION',
      'lower_limit_rate': '89.745',
      'lower_limit_source': 'table',
      'prdprc_range_bgn': '-2',
      'prdprc_range_end': 2,
      'a_value': '1234567',
      'a_value_source': 'tier0',
      'a_value_applicable': 'Y',
      'net_cost': '80000000',
    });

    expect(notice.basicPrice, 90000000);
    expect(notice.confirmedBasisAmount, 100000000);
    expect(notice.lowerLimitRate, 89.745);
    expect(notice.prdprcRangeBgn, -2);
    expect(notice.prdprcRangeEnd, 2);
    expect(notice.aValue, 1234567);
    expect(notice.aValueSource, 'tier0');
    expect(notice.aValueApplicable, 'Y');
    expect(notice.netCost, 80000000);
  });

  test('unconfirmed status never exposes basis even when an amount exists', () {
    final notice = Notice(
      bidNo: 'N-2',
      title: '테스트',
      content: '',
      basicPrice: 90000000,
      basisAmount: 100000000,
      basisStatus: 'unconfirmed',
    );

    expect(notice.confirmedBasisAmount, isNull);
  });

  test('basis amount without explicit status remains unconfirmed', () {
    final notice = Notice.fromJson({
      'bid_no': 'N-2A',
      'title': '테스트',
      'content': '',
      'basic_price': 90000000,
      'basis_amount': 100000000,
    });

    expect(notice.basisStatus, 'unconfirmed');
    expect(notice.confirmedBasisAmount, isNull);
  });

  test('context merge keeps estimated price distinct from confirmed basis', () {
    final notice = Notice(
      bidNo: 'N-3',
      title: '테스트',
      content: '',
      basicPrice: 90000000,
    ).withCalculationContext({
      'basis_amount': 100000000,
      'basis_status': 'confirmed',
      'lower_limit_rate': 89.745,
      'lower_limit_source': 'table',
      'contract_type': 'CONSTRUCTION',
    });

    expect(notice.basicPrice, 90000000);
    expect(notice.confirmedBasisAmount, 100000000);
    expect(notice.lowerLimitRate, 89.745);
  });

  test('AI analysis params label estimate and confirmed basis separately', () {
    final notice = Notice(
      bidNo: 'N-4',
      title: '분석 테스트',
      content: '',
      basicPrice: 90000000,
      basisAmount: 100000000,
      basisStatus: 'confirmed',
      lowerLimitRate: 89.745,
      prdprcRangeBgn: -2,
      prdprcRangeEnd: 2,
      aValue: 1234567,
      aValueSource: 'tier0',
      aValueApplicable: 'Y',
    );

    final params = notice.toAnalysisParams();
    expect(params['estimated_price'], '90000000.0');
    expect(params['basis_amount'], '100000000.0');
    expect(params['basis_status'], 'confirmed');
    expect(params['basic_price'], isNull);
    expect(params['a_value_source'], 'tier0');
  });
}
