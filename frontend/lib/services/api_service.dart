import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/notice.dart';
import '../models/ai_analysis.dart';

class ApiService {
  // Use 10.0.2.2 for Android emulator, localhost for Web/iOS/Windows
  // Since we are targeting Windows/Web, localhost is fine.
  static const String baseUrl = 'http://127.0.0.1:8000/api/v1';

  Future<List<Notice>> fetchNotices({String? keyword}) async {
    try {
      String url = '$baseUrl/bids/feed';
      if (keyword != null && keyword.isNotEmpty) {
        url += '?keyword=$keyword';
      }
      final response = await http.get(Uri.parse(url));

      if (response.statusCode == 200) {
        List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
        List<Notice> notices =
            body.map((dynamic item) => Notice.fromJson(item)).toList();
        return notices;
      } else {
        throw Exception('Failed to load notices: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load notices: $e');
    }
  }

  Future<void> triggerCrawl() async {
    try {
      final response = await http.post(Uri.parse('$baseUrl/bids/crawl'));
      if (response.statusCode != 200) {
        throw Exception('Failed to trigger crawl: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to trigger crawl: $e');
    }
  }

  // Future<BidCalculationResponse> calculateBid(...)
  // Implement this later when needed

  Future<AiAnalysis> fetchBidAnalysis(String bidNo) async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/ai/$bidNo/analysis'));

      if (response.statusCode == 200) {
        // Decode logic
        return AiAnalysis.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
      } else {
        throw Exception('Failed to load analysis: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load analysis: $e');
    }
  }
}
