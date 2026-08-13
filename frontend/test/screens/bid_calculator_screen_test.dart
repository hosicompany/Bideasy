import 'package:bideasy_app/models/notice.dart';
import 'package:bideasy_app/models/smart_bid.dart';
import 'package:bideasy_app/screens/bid_calculator_screen.dart';
import 'package:bideasy_app/services/api_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../helpers/mock_api_service.dart';

Notice _notice({bool confirmed = false}) => Notice(
      bidNo: 'N-CONTEXT',
      title: '테스트 공사',
      content: '',
      basicPrice: 90000000,
      basisAmount: confirmed ? 100000000 : null,
      basisStatus: confirmed ? 'confirmed' : 'unconfirmed',
      lowerLimitRate: confirmed ? 89.745 : null,
      contractType: 'CONSTRUCTION',
      bidType: '공사',
      bidMethod: confirmed ? '적격심사제' : null,
      organization: '테스트기관',
      aValue: confirmed ? 1000 : null,
      aValueSource: confirmed ? 'tier0' : null,
      aValueApplicable: confirmed ? 'Y' : null,
    );

SmartBidRecommendation _abstain() => SmartBidRecommendation.fromJson({
      'route': 'UNSUPPORTED',
      'decision_status': 'abstained',
      'abstain_reason': '테스트 기권',
    });

void _stubSmartBidAfterContext(MockApiService api) {
  when(
    () => api.getSmartRecommendation(
      baseAmount: 100000000,
      basisStatus: 'confirmed',
      bidType: 'construction',
      bidNo: 'N-CONTEXT',
      bidMethod: '적격심사제',
      contractMethod: null,
      aValue: 1000,
      aValueStatus: 'confirmed',
      lowerLimitRate: 89.745,
      prdprcRangeBgn: null,
      prdprcRangeEnd: null,
      estimatedAmount: null,
      agencyName: '테스트기관',
      bidDate: null,
    ),
  ).thenAnswer((_) async => _abstain());
}

void main() {
  testWidgets(
    'context merge sends confirmed basis to Smart Bid instead of estimate',
    (tester) async {
      final api = MockApiService();
      when(() => api.fetchBidContext('N-CONTEXT')).thenAnswer(
        (_) async => {
          'found': true,
          'basis_amount': 100000000,
          'basis_status': 'confirmed',
          'lower_limit_rate': 89.745,
          'lower_limit_source': 'table',
          'contract_type': 'CONSTRUCTION',
          'bid_method': '적격심사제',
          'a_value': 1000,
          'a_value_source': 'tier0',
          'a_value_applicable': 'Y',
        },
      );
      when(() => api.getDailyFreeStatus())
          .thenAnswer((_) async => {'available': true});
      _stubSmartBidAfterContext(api);

      await tester.pumpWidget(
        MaterialApp(
          home: BidCalculatorScreen(
            notice: _notice(),
            apiService: api,
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(find.byKey(const ValueKey('calculation-abstain')), findsNothing);
      verify(
        () => api.getSmartRecommendation(
          baseAmount: 100000000,
          basisStatus: 'confirmed',
          bidType: 'construction',
          bidNo: 'N-CONTEXT',
          bidMethod: '적격심사제',
          contractMethod: null,
          aValue: 1000,
          aValueStatus: 'confirmed',
          lowerLimitRate: 89.745,
          prdprcRangeBgn: null,
          prdprcRangeEnd: null,
          estimatedAmount: null,
          agencyName: '테스트기관',
          bidDate: null,
        ),
      ).called(1);
    },
  );

  testWidgets('server calculation failure never deducts points or copies', (
    tester,
  ) async {
    final api = MockApiService();
    when(() => api.getDailyFreeStatus())
        .thenAnswer((_) async => {'available': true});
    _stubSmartBidAfterContext(api);
    when(
      () => api.calculateBidDetailed(
        basicPrice: 100000000,
        rate: -5,
        aValueStatus: 'confirmed',
        contractType: 'CONSTRUCTION',
        aValue: 1000,
        lowerLimitRate: 89.745,
        bidDate: null,
      ),
    ).thenThrow(ApiException('검증 서버 오류'));

    await tester.pumpWidget(
      MaterialApp(
        home: BidCalculatorScreen(
          notice: _notice(confirmed: true),
          apiService: api,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    final copyButton = find.textContaining('투찰금액 복사하기');
    await tester.ensureVisible(copyButton);
    await tester.tap(copyButton);
    await tester.pump();

    expect(
      find.text('서버 계산을 검증하지 못해 복사하지 않았어요.'),
      findsOneWidget,
    );
    verifyNever(() => api.deductPoints(any()));
  });

  testWidgets('copies only the server-verified price after point deduction', (
    tester,
  ) async {
    String? clipboardText;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboardText =
              (call.arguments as Map<dynamic, dynamic>)['text']?.toString();
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null),
    );

    final api = MockApiService();
    when(() => api.getDailyFreeStatus())
        .thenAnswer((_) async => {'available': true});
    _stubSmartBidAfterContext(api);
    when(
      () => api.calculateBidDetailed(
        basicPrice: 100000000,
        rate: -5,
        aValueStatus: 'confirmed',
        contractType: 'CONSTRUCTION',
        aValue: 1000,
        lowerLimitRate: 89.745,
        bidDate: null,
      ),
    ).thenAnswer(
      (_) async => {
        'result_price': 95000050,
        'lower_limit_rate': 89.745,
        'safety_level': 'SAFE',
      },
    );
    when(() => api.deductPoints('N-CONTEXT'))
        .thenAnswer((_) async => {'was_free': true});

    await tester.pumpWidget(
      MaterialApp(
        home: BidCalculatorScreen(
          notice: _notice(confirmed: true),
          apiService: api,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    final copyButton = find.textContaining('투찰금액 복사하기');
    await tester.ensureVisible(copyButton);
    await tester.tap(copyButton);
    await tester.pump();

    verify(
      () => api.calculateBidDetailed(
        basicPrice: 100000000,
        rate: -5,
        aValueStatus: 'confirmed',
        contractType: 'CONSTRUCTION',
        aValue: 1000,
        lowerLimitRate: 89.745,
        bidDate: null,
      ),
    ).called(1);
    verify(() => api.deductPoints('N-CONTEXT')).called(1);
    expect(clipboardText, '95000050');
  });
}
