import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/models/agency_profile.dart';

void main() {
  group('AgencyProfile.fromJson', () {
    test('parses full response correctly', () {
      final json = {
        'organization': '강남구청',
        'total_bids': 150,
        'avg_winning_rate': 89.45,
        'min_winning_rate': 87.80,
        'max_winning_rate': 92.10,
        'avg_participants': 12.3,
        'avg_winning_price': 250000000.0,
        'winning_rate_distribution': {
          '87-88%': 5,
          '88-89%': 15,
          '89-90%': 45,
          '90-91%': 35,
          '91-92%': 20,
        },
        'recommendation': '평균 낙찰률 89.45%로 비교적 안정적입니다.',
      };

      final profile = AgencyProfile.fromJson(json);

      expect(profile.organization, '강남구청');
      expect(profile.totalBids, 150);
      expect(profile.avgWinningRate, 89.45);
      expect(profile.minWinningRate, 87.80);
      expect(profile.maxWinningRate, 92.10);
      expect(profile.avgParticipants, 12.3);
      expect(profile.avgWinningPrice, 250000000.0);
      expect(profile.winningRateDistribution.length, 5);
      expect(profile.recommendation, contains('89.45%'));
    });

    test('handles nullable fields gracefully', () {
      final json = {
        'organization': '테스트기관',
        'total_bids': 0,
      };

      final profile = AgencyProfile.fromJson(json);

      expect(profile.organization, '테스트기관');
      expect(profile.totalBids, 0);
      expect(profile.avgWinningRate, isNull);
      expect(profile.minWinningRate, isNull);
      expect(profile.maxWinningRate, isNull);
      expect(profile.avgParticipants, isNull);
      expect(profile.avgWinningPrice, isNull);
      expect(profile.winningRateDistribution, isEmpty);
      expect(profile.recommendation, '');
    });
  });
}
