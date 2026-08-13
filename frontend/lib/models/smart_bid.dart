import 'package:flutter/material.dart';

Map<String, dynamic> _asMap(dynamic value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  return <String, dynamic>{};
}

double _asDouble(dynamic value, [double fallback = 0]) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '') ?? fallback;
}

double? _asNullableDouble(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

int? _asNullableInt(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toInt();
  return int.tryParse(value.toString());
}

String? _asNullableString(dynamic value) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? null : text;
}

/// 경쟁 강도 5단계
enum CompetitionLevel {
  blueOcean,
  adequate,
  moderate,
  competitive,
  redOcean;

  String get label => switch (this) {
        blueOcean => '블루오션',
        adequate => '적정경쟁',
        moderate => '보통',
        competitive => '경쟁치열',
        redOcean => '레드오션',
      };

  String get emoji => switch (this) {
        blueOcean => '🔵',
        adequate => '🟢',
        moderate => '🟡',
        competitive => '🟠',
        redOcean => '🔴',
      };

  Color get color => switch (this) {
        blueOcean => const Color(0xFF3182F6),
        adequate => const Color(0xFF34C759),
        moderate => const Color(0xFFFFCC00),
        competitive => const Color(0xFFFF9500),
        redOcean => const Color(0xFFFF3B30),
      };

  String get range => switch (this) {
        blueOcean => '1-5명',
        adequate => '6-10명',
        moderate => '11-20명',
        competitive => '21-50명',
        redOcean => '51명+',
      };

  static CompetitionLevel fromBucket(int bucket) => switch (bucket) {
        0 => blueOcean,
        1 => adequate,
        2 => moderate,
        3 => competitive,
        _ => redOcean,
      };
}

/// 참여수 예측 결과
class CompetitionPrediction {
  final int predictedCount;
  final int predictedBucket;
  final String competitionLevel;
  final double blueOceanProbability;
  final String strategy;

  CompetitionPrediction({
    required this.predictedCount,
    required this.predictedBucket,
    required this.competitionLevel,
    required this.blueOceanProbability,
    required this.strategy,
  });

  CompetitionLevel get level => CompetitionLevel.fromBucket(predictedBucket);

  factory CompetitionPrediction.fromJson(Map<String, dynamic> json) {
    return CompetitionPrediction(
      predictedCount: json['predicted_count'] ?? 0,
      predictedBucket: json['predicted_bucket'] ?? 4,
      competitionLevel: json['competition_level'] ?? '',
      blueOceanProbability: (json['blue_ocean_probability'] ?? 0).toDouble(),
      strategy: json['strategy']?['description'] ?? '',
    );
  }
}

/// 스마트 투찰 추천 결과
class SmartBidRecommendation {
  final double optimalBid;
  final double lowerLimit;
  final String lowerLimitPct;
  final double appliedMarginPct;
  final double effectiveRate;
  final double expectedPlannedPriceMean;
  final double? expectedPlannedPriceLow;
  final double? expectedPlannedPriceHigh;
  final String? expectedPlannedPriceRangeSource;
  final String? expectedPlannedPriceRangeUnavailableReason;
  final double bidRateAtMean;
  final String tieRisk;
  final double dangerZone;
  final String recommendation;
  final CompetitionInfo? competition;
  final String recommendationId;
  final String? asOf;
  final String route;
  final String? strategyVersion;
  final String decisionStatus;
  final String? abstainCode;
  final String? abstainReason;
  final RecommendationEvidence? evidence;
  final RecommendationProbabilities? probabilities;
  final String? competitionUnavailableReason;

  SmartBidRecommendation({
    required this.optimalBid,
    required this.lowerLimit,
    required this.lowerLimitPct,
    required this.appliedMarginPct,
    required this.effectiveRate,
    required this.expectedPlannedPriceMean,
    required this.expectedPlannedPriceLow,
    required this.expectedPlannedPriceHigh,
    this.expectedPlannedPriceRangeSource,
    this.expectedPlannedPriceRangeUnavailableReason,
    required this.bidRateAtMean,
    required this.tieRisk,
    required this.dangerZone,
    required this.recommendation,
    this.competition,
    this.recommendationId = '',
    this.asOf,
    this.route = '',
    this.strategyVersion,
    this.decisionStatus = 'recommended',
    this.abstainCode,
    this.abstainReason,
    this.evidence,
    this.probabilities,
    this.competitionUnavailableReason,
  });

  bool get isAbstained =>
      decisionStatus == 'abstained' || abstainReason != null;

  String get routeLabel => switch (route) {
        'PRICE_DOMINANT' => '가격지배형',
        'QUALIFICATION' => '적격심사형',
        'COMPREHENSIVE' => '종합평가형',
        'NEGOTIATION' => '협상형',
        'UNSUPPORTED' => '지원 확인 필요',
        _ => '규칙 추천',
      };

  factory SmartBidRecommendation.fromJson(Map<String, dynamic> json) {
    final expectedPrice = _asMap(json['expected_planned_price']);
    final priceRange = _asMap(expectedPrice['range']);
    final bidRate = _asMap(json['bid_rate']);
    final competition = _asMap(json['competition']);
    final evidence = _asMap(json['evidence']);
    final probabilities = _asMap(json['probabilities']);

    return SmartBidRecommendation(
      optimalBid: _asDouble(json['optimal_bid']),
      lowerLimit: _asDouble(json['lower_limit']),
      lowerLimitPct: json['lower_limit_pct']?.toString() ?? '',
      appliedMarginPct: _asDouble(json['applied_margin_pct']),
      effectiveRate: _asDouble(json['effective_rate']),
      expectedPlannedPriceMean: _asDouble(expectedPrice['mean']),
      expectedPlannedPriceLow: _asNullableDouble(priceRange['low']),
      expectedPlannedPriceHigh: _asNullableDouble(priceRange['high']),
      expectedPlannedPriceRangeSource: _asNullableString(priceRange['source']),
      expectedPlannedPriceRangeUnavailableReason: _asNullableString(
        priceRange['unavailable_reason'],
      ),
      bidRateAtMean: _asDouble(bidRate['at_mean']),
      tieRisk: json['tie_risk']?.toString() ?? 'medium',
      dangerZone: _asDouble(json['danger_zone']),
      recommendation: json['recommendation']?.toString() ?? '',
      competition:
          competition.isNotEmpty ? CompetitionInfo.fromJson(competition) : null,
      recommendationId: json['recommendation_id']?.toString() ?? '',
      asOf: _asNullableString(json['as_of']),
      route: json['route']?.toString() ?? '',
      strategyVersion: _asNullableString(json['strategy_version']),
      decisionStatus: json['decision_status']?.toString() ?? 'recommended',
      abstainCode: _asNullableString(json['abstain_code']),
      abstainReason: _asNullableString(json['abstain_reason']),
      evidence: evidence.isNotEmpty
          ? RecommendationEvidence.fromJson(evidence)
          : null,
      probabilities: probabilities.isNotEmpty
          ? RecommendationProbabilities.fromJson(probabilities)
          : null,
      competitionUnavailableReason: _asNullableString(
        json['competition_unavailable_reason'],
      ),
    );
  }
}

class RecommendationEvidence {
  final String? basis;
  final String validationStatus;
  final String? bidNo;
  final String? bidMethod;
  final int? sampleSize;
  final String? latestObservationAt;

  RecommendationEvidence({
    this.basis,
    required this.validationStatus,
    this.bidNo,
    this.bidMethod,
    this.sampleSize,
    this.latestObservationAt,
  });

  factory RecommendationEvidence.fromJson(Map<String, dynamic> json) {
    return RecommendationEvidence(
      basis: _asNullableString(json['basis']),
      validationStatus: json['validation_status']?.toString() ?? 'not_provided',
      bidNo: _asNullableString(json['bid_no']),
      bidMethod: _asNullableString(json['bid_method']),
      sampleSize: _asNullableInt(json['sample_size']),
      latestObservationAt: _asNullableString(json['latest_observation_at']),
    );
  }
}

class RecommendationProbabilities {
  final double? belowLowerLimit;
  final double? priceRankOne;
  final double? finalAward;
  final String? unavailableReason;

  RecommendationProbabilities({
    this.belowLowerLimit,
    this.priceRankOne,
    this.finalAward,
    this.unavailableReason,
  });

  factory RecommendationProbabilities.fromJson(Map<String, dynamic> json) {
    return RecommendationProbabilities(
      belowLowerLimit: _asNullableDouble(json['below_lower_limit']),
      priceRankOne: _asNullableDouble(json['price_rank_one']),
      finalAward: _asNullableDouble(json['final_award']),
      unavailableReason: _asNullableString(json['unavailable_reason']),
    );
  }
}

/// 경쟁 분석 정보 (추천 결과 내 포함)
class CompetitionInfo {
  final int predictedParticipants;
  final String competitionLevel;
  final double blueOceanProbability;
  final double recommendedMargin;

  CompetitionInfo({
    required this.predictedParticipants,
    required this.competitionLevel,
    required this.blueOceanProbability,
    required this.recommendedMargin,
  });

  factory CompetitionInfo.fromJson(Map<String, dynamic> json) {
    return CompetitionInfo(
      predictedParticipants: json['predicted_participants'] ?? 0,
      competitionLevel: json['competition_level'] ?? '',
      blueOceanProbability: (json['blue_ocean_probability'] ?? 0).toDouble(),
      recommendedMargin: (json['recommended_margin'] ?? 0).toDouble(),
    );
  }
}

/// bidType 정규화 (한국어/영어 혼재 → 백엔드 기대값)
String normalizeBidType(String? raw) {
  if (raw == null || raw.trim().isEmpty) return 'unknown';
  final lower = raw.toLowerCase();
  if (lower.contains('물품') || lower.contains('goods')) return 'goods';
  if (lower.contains('용역') || lower.contains('service')) return 'service';
  if (lower.contains('공사') || lower.contains('construction')) {
    return 'construction';
  }
  return 'unknown';
}
