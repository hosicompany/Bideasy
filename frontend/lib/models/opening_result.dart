class OpeningResult {
  final int rank;
  final String company;
  final String ceo;
  final double bidPrice;
  final double bidRate;
  final String successState;
  final String note;

  OpeningResult({
    required this.rank,
    required this.company,
    required this.ceo,
    required this.bidPrice,
    required this.bidRate,
    required this.successState,
    required this.note,
  });

  factory OpeningResult.fromJson(Map<String, dynamic> json) {
    return OpeningResult(
      rank: json['rank'] ?? 0,
      company: json['company'] ?? '',
      ceo: json['ceo'] ?? '',
      bidPrice: (json['bid_price'] ?? 0).toDouble(),
      bidRate: (json['bid_rate'] ?? 0).toDouble(),
      successState: json['success_state'] ?? '',
      note: json['note'] ?? '',
    );
  }
}
