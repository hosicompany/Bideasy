import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/notice.dart';

class ApiService {
  // Use 10.0.2.2 for Android emulator, localhost for Web/iOS/Windows
  // Since we are targeting Windows/Web, localhost is fine.
  static const String baseUrl = 'http://127.0.0.1:8000/api/v1';

  Future<List<Notice>> fetchNotices() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/bids/feed'));

      if (response.statusCode == 200) {
        List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
        List<Notice> notices = body.map((dynamic item) => Notice.fromJson(item)).toList();
        return notices;
      } else {
        throw Exception('Failed to load notices: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load notices: $e');
    }
  }

  // Future<BidCalculationResponse> calculateBid(...) 
  // Implement this later when needed
}
