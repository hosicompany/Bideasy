import 'package:intl/intl.dart';

class Notice {
  final String bidNo;
  final String title;
  final double basicPrice;
  final DateTime? startDate;
  final DateTime? endDate;

  Notice({
    required this.bidNo,
    required this.title,
    required this.basicPrice,
    this.startDate,
    this.endDate,
  });

  // Factory for JSON parsing
  factory Notice.fromJson(Map<String, dynamic> json) {
    return Notice(
      bidNo: json['bid_no'] ?? '',
      title: json['title'] ?? '',
      basicPrice: (json['basic_price'] ?? 0).toDouble(),
      startDate: json['start_date'] != null ? DateTime.parse(json['start_date']) : null,
      endDate: json['end_date'] != null ? DateTime.parse(json['end_date']) : null,
    );
  }

  // Formatting helper
  String get formattedPrice {
    final formatter = NumberFormat('#,###');
    return formatter.format(basicPrice.toInt());
  }
}
