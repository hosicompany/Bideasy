import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/notice.dart';
import '../models/ai_analysis.dart';
import '../models/opening_result.dart';
import '../models/user.dart';

class ApiService {
  // Use 10.0.2.2 for Android emulator, 127.0.0.1 for Web/iOS/Windows
  // Using 127.0.0.1 avoids localhost resolution issues (IPv4 vs IPv6)
  static const String baseUrl = 'http://127.0.0.1:8000/api/v1';

  Future<List<Notice>> fetchNotices({
    String? keyword,
    bool excludeClosed = false,
    int page = 1,
  }) async {
    try {
      final queryParams = <String, String>{};
      if (keyword != null && keyword.isNotEmpty) {
        queryParams['keyword'] = keyword;
      }
      queryParams['exclude_closed'] = excludeClosed.toString();
      queryParams['page'] = page.toString();
      queryParams['limit'] = '20'; // Match backend limit

      final uri = Uri.parse(
        '$baseUrl/bids/feed',
      ).replace(queryParameters: queryParams);
      final response = await http.get(uri);

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

  Future<AiAnalysis> fetchBidAnalysis(
    String bidNo,
    Map<String, String> params,
  ) async {
    try {
      String url = '$baseUrl/ai/$bidNo/analysis';
      if (params.isNotEmpty) {
        url +=
            '?${params.entries.map((e) => '${e.key}=${Uri.encodeComponent(e.value)}').join('&')}';
      }

      final response = await http.get(Uri.parse(url));

      if (response.statusCode == 200) {
        return AiAnalysis.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
      } else {
        throw Exception('Failed to load analysis: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load analysis: $e');
    }
  }

  Future<void> toggleFavorite(String bidNo) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/bids/$bidNo/favorite'),
      );
      if (response.statusCode != 200) {
        throw Exception('Failed to toggle favorite: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to toggle favorite: $e');
    }
  }

  Future<List<Notice>> fetchFavorites() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/bids/favorites/list'),
      );
      if (response.statusCode == 200) {
        List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
        return body.map((dynamic item) => Notice.fromJson(item)).toList();
      } else {
        throw Exception('Failed to load favorites: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load favorites: $e');
    }
  }

  Future<List<OpeningResult>> fetchOpeningResults(String bidNo) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/bids/$bidNo/results'),
      );

      if (response.statusCode == 200) {
        List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
        return body
            .map((dynamic item) => OpeningResult.fromJson(item))
            .toList();
      } else {
        throw Exception('Failed to load results: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load results: $e');
    }
  }

  Future<User> getUserMe() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/users/me'));
      if (response.statusCode == 200) {
        return User.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
      } else {
        throw Exception('Failed to load user: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load user: $e');
    }
  }

  Future<User> updateUserMe(Map<String, dynamic> data) async {
    try {
      final response = await http.put(
        Uri.parse('$baseUrl/users/me'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(data),
      );
      if (response.statusCode == 200) {
        return User.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
      } else {
        throw Exception('Failed to update user: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to update user: $e');
    }
  }

  // ─── Points API ───

  Future<Map<String, dynamic>> getPointBalance() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/points/balance'));
      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        throw Exception('Failed to load balance: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load balance: $e');
    }
  }

  Future<Map<String, dynamic>> deductPoints(String bidNo) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/points/deduct'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'bid_no': bidNo}),
      );
      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else if (response.statusCode == 402) {
        final body = jsonDecode(utf8.decode(response.bodyBytes));
        throw Exception(body['detail'] ?? '포인트가 부족합니다');
      } else {
        throw Exception('Failed to deduct points: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('$e');
    }
  }

  Future<Map<String, dynamic>> chargePoints(int amount) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/points/charge'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'amount': amount}),
      );
      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        throw Exception('Failed to charge points: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to charge points: $e');
    }
  }

  Future<List<Map<String, dynamic>>> getPointHistory({int limit = 20}) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/points/history?limit=$limit'),
      );
      if (response.statusCode == 200) {
        final List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
        return body.cast<Map<String, dynamic>>();
      } else {
        throw Exception('Failed to load history: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('Failed to load history: $e');
    }
  }

  Future<Map<String, dynamic>> fetchScientificAnalysis(String bidNo) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/analysis/$bidNo/recommend points'),
      );
      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        throw Exception(
          'Failed to load scientific analysis: ${response.statusCode}',
        );
      }
    } catch (e) {
      throw Exception('Failed to load scientific analysis: $e');
    }
  }
}
