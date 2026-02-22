import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/models/deep_analysis.dart';

void main() {
  group('DeepAnalysis.fromJson', () {
    test('parses full response correctly', () {
      final json = {
        'bid_id': 'R25BK001',
        'bid_title': '도로 보수공사',
        'qualification_requirements': [
          {'category': '면허', 'content': '건축공사업 필수', 'importance': '필수'},
        ],
        'toxic_clauses': [
          {
            'type': '지체상금',
            'content': '일일 3/1000',
            'severity': 'HIGH',
            'recommendation': '계약 전 협의 필요',
          },
        ],
        'key_conditions': [
          {'category': '공사기간', 'content': '착공일로부터 180일', 'note': '동절기 포함'},
        ],
        'risk_assessment': 'MEDIUM',
        'summary': '지체상금이 높게 책정됨',
        'analyzed_files': ['규격서.hwp', '계약특수조건.pdf'],
        'error': null,
      };

      final result = DeepAnalysis.fromJson(json);

      expect(result.bidId, 'R25BK001');
      expect(result.bidTitle, '도로 보수공사');
      expect(result.qualificationRequirements.length, 1);
      expect(result.qualificationRequirements[0].category, '면허');
      expect(result.qualificationRequirements[0].importance, '필수');
      expect(result.toxicClauses.length, 1);
      expect(result.toxicClauses[0].severity, 'HIGH');
      expect(result.toxicClauses[0].recommendation, '계약 전 협의 필요');
      expect(result.keyConditions.length, 1);
      expect(result.keyConditions[0].note, '동절기 포함');
      expect(result.riskAssessment, 'MEDIUM');
      expect(result.summary, '지체상금이 높게 책정됨');
      expect(result.analyzedFiles, ['규격서.hwp', '계약특수조건.pdf']);
      expect(result.hasError, isFalse);
      expect(result.isEmpty, isFalse);
    });

    test('handles minimal/empty response', () {
      final json = {
        'bid_id': 'TEST001',
      };

      final result = DeepAnalysis.fromJson(json);

      expect(result.bidId, 'TEST001');
      expect(result.bidTitle, isNull);
      expect(result.qualificationRequirements, isEmpty);
      expect(result.toxicClauses, isEmpty);
      expect(result.keyConditions, isEmpty);
      expect(result.riskAssessment, 'LOW');
      expect(result.summary, '');
      expect(result.analyzedFiles, isEmpty);
      expect(result.hasError, isFalse);
      expect(result.isEmpty, isTrue);
    });

    test('handles error response', () {
      final json = {
        'bid_id': 'TEST002',
        'error': '첨부파일을 찾을 수 없습니다.',
      };

      final result = DeepAnalysis.fromJson(json);

      expect(result.hasError, isTrue);
      expect(result.error, '첨부파일을 찾을 수 없습니다.');
    });
  });

  group('QualificationRequirement.fromJson', () {
    test('uses default importance when not provided', () {
      final req = QualificationRequirement.fromJson({
        'category': '실적',
        'content': '유사 실적 3건 이상',
      });

      expect(req.importance, '권장');
    });
  });

  group('ToxicClause.fromJson', () {
    test('uses default severity when not provided', () {
      final clause = ToxicClause.fromJson({
        'type': '하자보수',
        'content': '하자보수 보증금 5%',
      });

      expect(clause.severity, 'MEDIUM');
      expect(clause.recommendation, isNull);
    });
  });
}
