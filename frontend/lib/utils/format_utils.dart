import 'package:intl/intl.dart';

/// Format price in Korean style (억원, 만원, 원).
String formatPriceKorean(double price) {
  if (price >= 100000000) {
    return '${(price / 100000000).toStringAsFixed(1)}억원';
  } else if (price >= 10000) {
    return '${(price / 10000).toStringAsFixed(0)}만원';
  }
  return '${NumberFormat('#,###').format(price.toInt())}원';
}
