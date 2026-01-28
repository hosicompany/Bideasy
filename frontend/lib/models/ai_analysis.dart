/// Enhanced AI Analysis Model
/// 환각 방지 규칙 기반 분석 결과를 위한 모델

enum AnalysisSentiment { safe, caution, danger }

/// 개선된 AI 분석 결과
class AiAnalysis {
  final String summary;
  final EligibilityInfo eligibility;
  final List<BidTip> tips;
  final DeadlineInfo deadlineInfo;
  final PriceInfo priceInfo;
  final AnalysisSentiment sentiment;
  final AValueInfo? aValueInfo;
  final int? netCost;

  AiAnalysis({
    required this.summary,
    required this.eligibility,
    required this.tips,
    required this.deadlineInfo,
    required this.priceInfo,
    required this.sentiment,
    this.aValueInfo,
    this.netCost,
  });

  factory AiAnalysis.fromJson(Map<String, dynamic> json) {
    // tips 파싱
    final tipsList = (json['tips'] as List?)
            ?.map((e) => BidTip.fromJson(e as Map<String, dynamic>))
            .toList() ??
        [];

    // HIGH importance 팁이 있거나 긴급 마감이면 caution
    AnalysisSentiment parsedSentiment = AnalysisSentiment.safe;

    final hasHighImportance = tipsList.any((tip) => tip.importance == 'HIGH');
    final deadlineData = json['deadline_info'] as Map<String, dynamic>?;
    final isUrgent = deadlineData?['is_urgent'] == true;

    if (isUrgent || hasHighImportance) {
      parsedSentiment = AnalysisSentiment.caution;
    }

    return AiAnalysis(
      summary: json['summary'] ?? '',
      eligibility: EligibilityInfo.fromJson(
          json['eligibility'] as Map<String, dynamic>? ?? {}),
      tips: tipsList,
      deadlineInfo: DeadlineInfo.fromJson(
          json['deadline_info'] as Map<String, dynamic>? ?? {}),
      priceInfo:
          PriceInfo.fromJson(json['price_info'] as Map<String, dynamic>? ?? {}),
      sentiment: parsedSentiment,
      aValueInfo: json['a_value_info'] != null
          ? AValueInfo.fromJson(json['a_value_info'] as Map<String, dynamic>)
          : null,
      netCost: json['net_cost'] as int?,
    );
  }

  /// 중요도 순으로 정렬된 팁 반환
  List<BidTip> get sortedTips {
    final sorted = List<BidTip>.from(tips);
    sorted.sort((a, b) {
      const order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2};
      return (order[a.importance] ?? 3).compareTo(order[b.importance] ?? 3);
    });
    return sorted;
  }

  /// 카테고리별 팁 필터
  List<BidTip> tipsByCategory(String category) {
    return tips.where((tip) => tip.category == category).toList();
  }
}

/// A값 정보
class AValueInfo {
  final int total;
  final bool found;
  final Map<String, int> breakdown;

  AValueInfo({
    required this.total,
    required this.found,
    required this.breakdown,
  });

  factory AValueInfo.fromJson(Map<String, dynamic> json) {
    return AValueInfo(
      total: json['total'] as int? ?? 0,
      found: json['found'] == true,
      breakdown: (json['breakdown'] as Map<String, dynamic>?)?.map(
            (k, v) => MapEntry(k, v as int),
          ) ??
          {},
    );
  }
}

/// 참가 자격 정보
class EligibilityInfo {
  final bool? canParticipate;
  final List<String> requirements;
  final String source;

  EligibilityInfo({
    this.canParticipate,
    required this.requirements,
    required this.source,
  });

  factory EligibilityInfo.fromJson(Map<String, dynamic> json) {
    return EligibilityInfo(
      canParticipate: json['can_participate'] as bool?,
      requirements: List<String>.from(json['requirements'] ?? []),
      source: json['source'] ?? '',
    );
  }

  bool get hasRestrictions => requirements.isNotEmpty;
}

/// 마감 정보
class DeadlineInfo {
  final String? endDate;
  final String? openingDate;
  final int? daysRemaining;
  final bool isUrgent;
  final String source;

  DeadlineInfo({
    this.endDate,
    this.openingDate,
    this.daysRemaining,
    required this.isUrgent,
    required this.source,
  });

  factory DeadlineInfo.fromJson(Map<String, dynamic> json) {
    return DeadlineInfo(
      endDate: json['end_date']?.toString(),
      openingDate: json['opening_date']?.toString(),
      daysRemaining: json['days_remaining'] as int?,
      isUrgent: json['is_urgent'] == true,
      source: json['source'] ?? '',
    );
  }
}

/// 가격 정보
class PriceInfo {
  final double? basicPrice;
  final String? basicPriceFormatted;
  final EstimatedPriceRange? estimatedPriceRange;
  final LowerLimit? lowerLimit;
  final double? budget;
  final String source;

  PriceInfo({
    this.basicPrice,
    this.basicPriceFormatted,
    this.estimatedPriceRange,
    this.lowerLimit,
    this.budget,
    required this.source,
  });

  factory PriceInfo.fromJson(Map<String, dynamic> json) {
    return PriceInfo(
      basicPrice: (json['basic_price'] as num?)?.toDouble(),
      basicPriceFormatted: json['basic_price_formatted']?.toString(),
      estimatedPriceRange: json['estimated_price_range'] != null
          ? EstimatedPriceRange.fromJson(
              json['estimated_price_range'] as Map<String, dynamic>)
          : null,
      lowerLimit: json['lower_limit'] != null
          ? LowerLimit.fromJson(json['lower_limit'] as Map<String, dynamic>)
          : null,
      budget: (json['budget'] as num?)?.toDouble(),
      source: json['source'] ?? '',
    );
  }
}

/// 예정가격 범위
class EstimatedPriceRange {
  final double min;
  final double max;
  final String minFormatted;
  final String maxFormatted;

  EstimatedPriceRange({
    required this.min,
    required this.max,
    required this.minFormatted,
    required this.maxFormatted,
  });

  factory EstimatedPriceRange.fromJson(Map<String, dynamic> json) {
    return EstimatedPriceRange(
      min: (json['min'] as num?)?.toDouble() ?? 0,
      max: (json['max'] as num?)?.toDouble() ?? 0,
      minFormatted: json['min_formatted'] ?? '',
      maxFormatted: json['max_formatted'] ?? '',
    );
  }
}

/// 낙찰하한선
class LowerLimit {
  final double rate;
  final double amount;
  final String formatted;

  LowerLimit({
    required this.rate,
    required this.amount,
    required this.formatted,
  });

  factory LowerLimit.fromJson(Map<String, dynamic> json) {
    return LowerLimit(
      rate: (json['rate'] as num?)?.toDouble() ?? 0,
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      formatted: json['formatted'] ?? '',
    );
  }
}

/// 입찰 전략 팁
class BidTip {
  final String
      category; // eligibility, deadline, price, restriction, document, strategy
  final String icon;
  final String title;
  final String content;
  final String source;
  final String importance; // HIGH, MEDIUM, LOW
  final String? forBeginners; // 초보자용 추가 설명

  BidTip({
    required this.category,
    required this.icon,
    required this.title,
    required this.content,
    required this.source,
    required this.importance,
    this.forBeginners,
  });

  factory BidTip.fromJson(Map<String, dynamic> json) {
    return BidTip(
      category: json['category'] ?? '',
      icon: json['icon'] ?? '💡',
      title: json['title'] ?? '',
      content: json['content'] ?? '',
      source: json['source'] ?? '',
      importance: json['importance'] ?? 'LOW',
      forBeginners: json['for_beginners'],
    );
  }

  /// 아이콘 색상 (중요도 기반)
  String get importanceColor {
    switch (importance) {
      case 'HIGH':
        return '#FF5252'; // Red
      case 'MEDIUM':
        return '#FFA726'; // Orange
      default:
        return '#66BB6A'; // Green
    }
  }
}
