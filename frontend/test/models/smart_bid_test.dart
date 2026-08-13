import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/models/smart_bid.dart';

void main() {
  test('parses additive recommendation evidence without breaking legacy fields',
      () {
    final recommendation = SmartBidRecommendation.fromJson({
      'recommendation_id': 'rec-1',
      'as_of': '2026-08-13T00:00:00Z',
      'route': 'QUALIFICATION',
      'strategy_version': 'v1',
      'decision_status': 'recommended',
      'optimal_bid': 90123450,
      'lower_limit': 0.89745,
      'lower_limit_pct': '89.745%',
      'applied_margin_pct': 0.2,
      'effective_rate': 89.945,
      'expected_planned_price': {
        'mean': 100000000,
        'range': {
          'low': 98000000,
          'high': 102000000,
          'source': 'notice_public_range',
          'unavailable_reason': null,
        },
      },
      'bid_rate': {'at_mean': 90.12345},
      'tie_risk': 'medium',
      'danger_zone': 89745000,
      'recommendation': '규칙 추천',
      'evidence': {
        'basis': 'autocalibrate_rule_based',
        'validation_status': 'probability_not_calibrated',
        'bid_no': 'N-1',
        'bid_method': '적격심사제',
      },
      'probabilities': {
        'below_lower_limit': null,
        'price_rank_one': null,
        'final_award': null,
        'unavailable_reason': '아직 검증 전',
      },
    });

    expect(recommendation.optimalBid, 90123450);
    expect(recommendation.recommendationId, 'rec-1');
    expect(recommendation.routeLabel, '적격심사형');
    expect(recommendation.strategyVersion, 'v1');
    expect(recommendation.isAbstained, isFalse);
    expect(recommendation.evidence?.bidMethod, '적격심사제');
    expect(recommendation.probabilities?.priceRankOne, isNull);
    expect(recommendation.probabilities?.unavailableReason, '아직 검증 전');
    expect(recommendation.expectedPlannedPriceLow, 98000000);
    expect(recommendation.expectedPlannedPriceHigh, 102000000);
    expect(
      recommendation.expectedPlannedPriceRangeSource,
      'notice_public_range',
    );
  });

  test('parses explicit abstain null values safely', () {
    final recommendation = SmartBidRecommendation.fromJson({
      'route': 'NEGOTIATION',
      'decision_status': 'abstained',
      'abstain_code': 'unsupported_bid_method',
      'abstain_reason': '검증된 전략이 없어요.',
      'optimal_bid': null,
      'expected_planned_price': {
        'mean': null,
        'range': {'low': null, 'high': null},
      },
      'bid_rate': {'at_mean': null},
    });

    expect(recommendation.isAbstained, isTrue);
    expect(recommendation.optimalBid, 0);
    expect(recommendation.routeLabel, '협상형');
    expect(recommendation.abstainReason, '검증된 전략이 없어요.');
  });

  test('legacy response still parses', () {
    final recommendation = SmartBidRecommendation.fromJson({
      'optimal_bid': 90000000,
      'expected_planned_price': {},
      'bid_rate': {},
    });

    expect(recommendation.optimalBid, 90000000);
    expect(recommendation.isAbstained, isFalse);
    expect(recommendation.routeLabel, '규칙 추천');
    expect(recommendation.expectedPlannedPriceLow, isNull);
    expect(recommendation.expectedPlannedPriceHigh, isNull);
  });

  test('missing public planned-price range stays null with its reason', () {
    final recommendation = SmartBidRecommendation.fromJson({
      'optimal_bid': 90000000,
      'expected_planned_price': {
        'mean': 99700000,
        'range': {
          'low': null,
          'high': null,
          'source': null,
          'unavailable_reason': '공고에서 범위를 확인하지 못했어요.',
        },
      },
      'bid_rate': {'at_mean': 90.1},
    });

    expect(recommendation.expectedPlannedPriceLow, isNull);
    expect(recommendation.expectedPlannedPriceHigh, isNull);
    expect(
      recommendation.expectedPlannedPriceRangeUnavailableReason,
      '공고에서 범위를 확인하지 못했어요.',
    );
  });

  test('unknown bid type is not silently treated as construction', () {
    expect(normalizeBidType(null), 'unknown');
    expect(normalizeBidType('알 수 없음'), 'unknown');
    expect(normalizeBidType('시설공사'), 'construction');
  });
}
