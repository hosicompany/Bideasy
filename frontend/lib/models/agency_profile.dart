/// Model for agency profiling — historical bid pattern analysis.
/// Maps to backend `AgencyProfile` schema.

class AgencyProfile {
  final String organization;
  final int totalBids;
  final double? avgWinningRate;
  final double? minWinningRate;
  final double? maxWinningRate;
  final double? avgParticipants;
  final double? avgWinningPrice;
  final Map<String, dynamic> winningRateDistribution;
  final String recommendation;

  const AgencyProfile({
    required this.organization,
    required this.totalBids,
    this.avgWinningRate,
    this.minWinningRate,
    this.maxWinningRate,
    this.avgParticipants,
    this.avgWinningPrice,
    this.winningRateDistribution = const {},
    this.recommendation = '',
  });

  factory AgencyProfile.fromJson(Map<String, dynamic> json) {
    return AgencyProfile(
      organization: json['organization'] as String,
      totalBids: json['total_bids'] as int,
      avgWinningRate: (json['avg_winning_rate'] as num?)?.toDouble(),
      minWinningRate: (json['min_winning_rate'] as num?)?.toDouble(),
      maxWinningRate: (json['max_winning_rate'] as num?)?.toDouble(),
      avgParticipants: (json['avg_participants'] as num?)?.toDouble(),
      avgWinningPrice: (json['avg_winning_price'] as num?)?.toDouble(),
      winningRateDistribution:
          json['winning_rate_distribution'] as Map<String, dynamic>? ?? {},
      recommendation: json['recommendation'] as String? ?? '',
    );
  }
}
