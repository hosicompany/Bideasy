import 'package:bideasy_app/models/notice.dart';
import 'package:bideasy_app/models/smart_bid.dart';
import 'package:bideasy_app/services/api_service.dart';
import 'package:bideasy_app/widgets/smart_bid_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../helpers/mock_api_service.dart';

Notice _notice({String bidMethod = '적격심사제'}) => Notice(
      bidNo: 'N-1',
      title: '테스트 공사',
      content: '',
      basicPrice: 100000000,
      basisAmount: 100000000,
      basisStatus: 'confirmed',
      bidType: 'construction',
      bidMethod: bidMethod,
      lowerLimitRate: 89.745,
      prdprcRangeBgn: -2,
      prdprcRangeEnd: 2,
      organization: '테스트기관',
      aValueApplicable: 'N',
    );

SmartBidRecommendation _recommended() => SmartBidRecommendation.fromJson({
      'recommendation_id': 'rec-1',
      'route': 'QUALIFICATION',
      'decision_status': 'recommended',
      'optimal_bid': 90123450,
      'lower_limit': 0.89745,
      'lower_limit_pct': '89.745%',
      'applied_margin_pct': 0.2,
      'effective_rate': 89.945,
      'expected_planned_price': {
        'mean': 100000000,
        'range': {'low': 97000000, 'high': 103000000},
      },
      'bid_rate': {'at_mean': 90.12345},
      'tie_risk': 'medium',
      'danger_zone': 89745000,
      'recommendation': '규칙 기반 추천이에요.',
      'probabilities': {'unavailable_reason': '확률은 아직 검증 중이에요.'},
    });

Notice _noticeWithAValue() => Notice(
      bidNo: 'N-A',
      title: '테스트 A값 공사',
      content: '',
      basicPrice: 90000000,
      basisAmount: 100000000,
      basisStatus: 'confirmed',
      bidType: 'construction',
      bidMethod: '적격심사제',
      lowerLimitRate: 88.2,
      organization: '테스트기관',
      aValue: 10000000,
      aValueSource: 'tier0',
      aValueApplicable: 'Y',
    );

void _stubCompetitionFailure(MockApiService api) {
  when(
    () => api.predictCompetition(
      bidType: 'construction',
      estimatedAmount: 100000000,
      agencyName: '테스트기관',
      bidDate: null,
    ),
  ).thenThrow(ApiException('선택 ML 준비 중', statusCode: 503));
}

void _stubExposure(MockApiService api, String recommendationId) {
  when(
    () => api.recordRecommendationDecision(
      recommendationId: recommendationId,
      eventType: 'EXPOSED',
      idempotencyKey: '$recommendationId:exposed',
      selectedPolicy: 'balanced',
      details: any(named: 'details'),
    ),
  ).thenAnswer((_) async {});
  when(
    () => api.recordRecommendationDecision(
      recommendationId: recommendationId,
      eventType: 'APPLIED',
      idempotencyKey: '$recommendationId:applied',
      selectedPolicy: 'balanced',
      details: any(named: 'details'),
    ),
  ).thenAnswer((_) async {});
}

void main() {
  testWidgets('optional competition failure does not hide rule recommendation',
      (
    tester,
  ) async {
    final api = MockApiService();
    double? appliedRate;
    _stubCompetitionFailure(api);
    _stubExposure(api, 'rec-1');
    when(
      () => api.getSmartRecommendation(
        baseAmount: 100000000,
        basisStatus: 'confirmed',
        bidType: 'construction',
        bidNo: 'N-1',
        bidMethod: '적격심사제',
        contractMethod: null,
        aValue: 0,
        aValueStatus: 'not_applicable',
        lowerLimitRate: 89.745,
        prdprcRangeBgn: -2,
        prdprcRangeEnd: 2,
        estimatedAmount: null,
        agencyName: '테스트기관',
        bidDate: null,
      ),
    ).thenAnswer((_) async => _recommended());

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SmartBidCard(
            notice: _notice(),
            apiService: api,
            onApplyRate: (rate, _, __) => appliedRate = rate,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('✨ 스마트 투찰 추천'), findsOneWidget);
    expect(find.text('적격심사형'), findsOneWidget);
    expect(find.text('규칙 기반 추천이에요.'), findsOneWidget);
    expect(find.text('투찰 추천을 불러올 수 없습니다'), findsNothing);
    expect(find.text('예상 참여 업체수'), findsNothing);
    verify(
      () => api.getSmartRecommendation(
        baseAmount: 100000000,
        basisStatus: 'confirmed',
        bidType: 'construction',
        bidNo: 'N-1',
        bidMethod: '적격심사제',
        contractMethod: null,
        aValue: 0,
        aValueStatus: 'not_applicable',
        lowerLimitRate: 89.745,
        prdprcRangeBgn: -2,
        prdprcRangeEnd: 2,
        estimatedAmount: null,
        agencyName: '테스트기관',
        bidDate: null,
      ),
    ).called(1);

    await tester.tap(find.text('이 가격으로 적용하기'));
    await tester.pump();
    expect(appliedRate, closeTo(-9.87655, 0.0001));
    verify(
      () => api.recordRecommendationDecision(
        recommendationId: 'rec-1',
        eventType: 'APPLIED',
        idempotencyKey: 'rec-1:applied',
        selectedPolicy: 'balanced',
        details: any(named: 'details'),
      ),
    ).called(1);
    verify(
      () => api.recordRecommendationDecision(
        recommendationId: 'rec-1',
        eventType: 'EXPOSED',
        idempotencyKey: 'rec-1:exposed',
        selectedPolicy: 'balanced',
        details: any(named: 'details'),
      ),
    ).called(1);
  });

  testWidgets('abstain response shows reason and never exposes apply button', (
    tester,
  ) async {
    final api = MockApiService();
    _stubCompetitionFailure(api);
    when(
      () => api.getSmartRecommendation(
        baseAmount: 100000000,
        basisStatus: 'confirmed',
        bidType: 'construction',
        bidNo: 'N-1',
        bidMethod: '협상에의한계약',
        contractMethod: null,
        aValue: 0,
        aValueStatus: 'not_applicable',
        lowerLimitRate: 89.745,
        prdprcRangeBgn: -2,
        prdprcRangeEnd: 2,
        estimatedAmount: null,
        agencyName: '테스트기관',
        bidDate: null,
      ),
    ).thenAnswer(
      (_) async => SmartBidRecommendation.fromJson({
        'route': 'NEGOTIATION',
        'decision_status': 'abstained',
        'abstain_reason': '이 입찰방법은 아직 검증된 전략이 없어요.',
        'evidence': {
          'validation_status': 'probability_not_calibrated',
          'bid_method': '협상에의한계약',
        },
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SmartBidCard(
            notice: _notice(bidMethod: '협상에의한계약'),
            apiService: api,
            onApplyRate: (_, __, ___) {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('추천가를 제시하지 않았어요'), findsOneWidget);
    expect(find.text('협상형'), findsOneWidget);
    expect(find.text('이 입찰방법은 아직 검증된 전략이 없어요.'), findsOneWidget);
    expect(find.text('이 가격으로 적용하기'), findsNothing);
  });

  testWidgets('A-value recommendation applies inverse calculator rate', (
    tester,
  ) async {
    final api = MockApiService();
    double? appliedRate;
    final recommendation = SmartBidRecommendation.fromJson({
      'recommendation_id': 'rec-a',
      'route': 'QUALIFICATION',
      'decision_status': 'recommended',
      'optimal_bid': 90123450,
      'lower_limit': 0.882,
      'lower_limit_pct': '88.200%',
      'applied_margin_pct': 0.2,
      'effective_rate': 88.4,
      'expected_planned_price': {
        'mean': 100000000,
        'range': {
          'low': null,
          'high': null,
          'unavailable_reason': '공고 범위 미확인',
        },
      },
      // (90,123,450 - 10,000,000) / 90,000,000 * 100
      'bid_rate': {'at_mean': 89.02605555555556},
      'tie_risk': 'medium',
      'danger_zone': 89380000,
      'recommendation': 'A값 규칙 추천이에요.',
      'probabilities': {'unavailable_reason': '확률은 검증 중'},
    });
    _stubCompetitionFailure(api);
    _stubExposure(api, 'rec-a');
    when(
      () => api.getSmartRecommendation(
        baseAmount: 100000000,
        basisStatus: 'confirmed',
        bidType: 'construction',
        bidNo: 'N-A',
        bidMethod: '적격심사제',
        contractMethod: null,
        aValue: 10000000,
        aValueStatus: 'confirmed',
        lowerLimitRate: 88.2,
        prdprcRangeBgn: null,
        prdprcRangeEnd: null,
        estimatedAmount: null,
        agencyName: '테스트기관',
        bidDate: null,
      ),
    ).thenAnswer((_) async => recommendation);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SmartBidCard(
            notice: _noticeWithAValue(),
            apiService: api,
            onApplyRate: (rate, _, __) => appliedRate = rate,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('이 가격으로 적용하기'));
    await tester.pump();

    expect(appliedRate, closeTo(-10.97394444444444, 0.0000001));
    final reproduced =
        ((((100000000 - 10000000) * (1 + appliedRate! / 100)) + 10000000) / 10)
                .floor() *
            10;
    expect(reproduced, 90123450);
  });
}
