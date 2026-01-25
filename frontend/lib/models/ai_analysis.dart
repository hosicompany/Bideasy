class AiAnalysis {
  final List<String> badges;
  final List<AnalysisCheckItem> checkItems;
  final List<String> tips;

  AiAnalysis({
    required this.badges,
    required this.checkItems,
    required this.tips,
  });

  factory AiAnalysis.fromJson(Map<String, dynamic> json) {
    return AiAnalysis(
      badges: List<String>.from(json['badges'] ?? []),
      checkItems: (json['check_items'] as List?)
              ?.map((e) => AnalysisCheckItem.fromJson(e))
              .toList() ??
          [],
      tips: List<String>.from(json['tips'] ?? []),
    );
  }
}

class AnalysisCheckItem {
  final String status; // OK, WARN, INFO
  final String label; // 지역, 실적, 면허
  final String text; // 세부 내용

  AnalysisCheckItem({
    required this.status,
    required this.label,
    required this.text,
  });

  factory AnalysisCheckItem.fromJson(Map<String, dynamic> json) {
    return AnalysisCheckItem(
      status: json['status'] ?? 'INFO',
      label: json['label'] ?? '',
      text: json['text'] ?? '',
    );
  }
}
