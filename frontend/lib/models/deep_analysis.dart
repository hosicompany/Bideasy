/// Models for deep analysis of bid attachments (HWP/PDF).
/// Maps to backend `DeepAnalysisResponse` schema.

class QualificationRequirement {
  final String category;
  final String content;
  final String importance;

  const QualificationRequirement({
    required this.category,
    required this.content,
    this.importance = '권장',
  });

  factory QualificationRequirement.fromJson(Map<String, dynamic> json) {
    return QualificationRequirement(
      category: json['category'] as String,
      content: json['content'] as String,
      importance: json['importance'] as String? ?? '권장',
    );
  }
}

class ToxicClause {
  final String type;
  final String content;
  final String severity;
  final String? recommendation;

  const ToxicClause({
    required this.type,
    required this.content,
    this.severity = 'MEDIUM',
    this.recommendation,
  });

  factory ToxicClause.fromJson(Map<String, dynamic> json) {
    return ToxicClause(
      type: json['type'] as String,
      content: json['content'] as String,
      severity: json['severity'] as String? ?? 'MEDIUM',
      recommendation: json['recommendation'] as String?,
    );
  }
}

class KeyCondition {
  final String category;
  final String content;
  final String? note;

  const KeyCondition({
    required this.category,
    required this.content,
    this.note,
  });

  factory KeyCondition.fromJson(Map<String, dynamic> json) {
    return KeyCondition(
      category: json['category'] as String,
      content: json['content'] as String,
      note: json['note'] as String?,
    );
  }
}

class DeepAnalysis {
  final String bidId;
  final String? bidTitle;
  final List<QualificationRequirement> qualificationRequirements;
  final List<ToxicClause> toxicClauses;
  final List<KeyCondition> keyConditions;
  final String riskAssessment;
  final String summary;
  final List<String> analyzedFiles;
  final String? error;

  const DeepAnalysis({
    required this.bidId,
    this.bidTitle,
    this.qualificationRequirements = const [],
    this.toxicClauses = const [],
    this.keyConditions = const [],
    this.riskAssessment = 'LOW',
    this.summary = '',
    this.analyzedFiles = const [],
    this.error,
  });

  factory DeepAnalysis.fromJson(Map<String, dynamic> json) {
    return DeepAnalysis(
      bidId: json['bid_id'] as String,
      bidTitle: json['bid_title'] as String?,
      qualificationRequirements: (json['qualification_requirements'] as List?)
              ?.map((e) =>
                  QualificationRequirement.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      toxicClauses: (json['toxic_clauses'] as List?)
              ?.map((e) => ToxicClause.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      keyConditions: (json['key_conditions'] as List?)
              ?.map((e) => KeyCondition.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      riskAssessment: json['risk_assessment'] as String? ?? 'LOW',
      summary: json['summary'] as String? ?? '',
      analyzedFiles: (json['analyzed_files'] as List?)
              ?.map((e) => e as String)
              .toList() ??
          [],
      error: json['error'] as String?,
    );
  }

  bool get hasError => error != null;
  bool get isEmpty =>
      qualificationRequirements.isEmpty &&
      toxicClauses.isEmpty &&
      keyConditions.isEmpty;
}
