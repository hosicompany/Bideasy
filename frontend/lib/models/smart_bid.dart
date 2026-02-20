import 'package:flutter/material.dart';

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
      blueOceanProbability:
          (json['blue_ocean_probability'] ?? 0).toDouble(),
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
  final double expectedPlannedPriceLow;
  final double expectedPlannedPriceHigh;
  final double bidRateAtMean;
  final String tieRisk;
  final double dangerZone;
  final String recommendation;
  final CompetitionInfo? competition;

  SmartBidRecommendation({
    required this.optimalBid,
    required this.lowerLimit,
    required this.lowerLimitPct,
    required this.appliedMarginPct,
    required this.effectiveRate,
    required this.expectedPlannedPriceMean,
    required this.expectedPlannedPriceLow,
    required this.expectedPlannedPriceHigh,
    required this.bidRateAtMean,
    required this.tieRisk,
    required this.dangerZone,
    required this.recommendation,
    this.competition,
  });

  factory SmartBidRecommendation.fromJson(Map<String, dynamic> json) {
    final expectedPrice = json['expected_planned_price'] ?? {};
    final priceRange = expectedPrice['range'] ?? {};
    final bidRate = json['bid_rate'] ?? {};

    return SmartBidRecommendation(
      optimalBid: (json['optimal_bid'] ?? 0).toDouble(),
      lowerLimit: (json['lower_limit'] ?? 0).toDouble(),
      lowerLimitPct: json['lower_limit_pct'] ?? '',
      appliedMarginPct: (json['applied_margin_pct'] ?? 0).toDouble(),
      effectiveRate: (json['effective_rate'] ?? 0).toDouble(),
      expectedPlannedPriceMean: (expectedPrice['mean'] ?? 0).toDouble(),
      expectedPlannedPriceLow: (priceRange['low'] ?? 0).toDouble(),
      expectedPlannedPriceHigh: (priceRange['high'] ?? 0).toDouble(),
      bidRateAtMean: (bidRate['at_mean'] ?? 0).toDouble(),
      tieRisk: json['tie_risk'] ?? 'medium',
      dangerZone: (json['danger_zone'] ?? 0).toDouble(),
      recommendation: json['recommendation'] ?? '',
      competition: json['competition'] != null
          ? CompetitionInfo.fromJson(json['competition'])
          : null,
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
      blueOceanProbability:
          (json['blue_ocean_probability'] ?? 0).toDouble(),
      recommendedMargin: (json['recommended_margin'] ?? 0).toDouble(),
    );
  }
}

/// bidType 정규화 (한국어/영어 혼재 → 백엔드 기대값)
String normalizeBidType(String? raw) {
  if (raw == null || raw.isEmpty) return 'construction';
  final lower = raw.toLowerCase();
  if (lower.contains('물품') || lower.contains('goods')) return 'goods';
  if (lower.contains('용역') || lower.contains('service')) return 'service';
  return 'construction';
}
