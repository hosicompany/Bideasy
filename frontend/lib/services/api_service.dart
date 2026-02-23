import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/notice.dart';
import '../models/ai_analysis.dart';
import '../models/opening_result.dart';
import '../models/user.dart';
import '../models/smart_bid.dart';
import '../models/deep_analysis.dart';
import '../models/agency_profile.dart';

class AuthException implements Exception {
  final String message;
  AuthException(this.message);

  @override
  String toString() => message;
}

class ApiException implements Exception {
  final String message;
  final int? statusCode;
  ApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class ApiService {
  // Use 10.0.2.2 for Android emulator, 127.0.0.1 for Web/iOS/Windows
  // Using 127.0.0.1 avoids localhost resolution issues (IPv4 vs IPv6)
  static const String baseUrl = 'http://127.0.0.1:8000/api/v1';
  static const Duration _timeout = Duration(seconds: 30);

  /// Wraps an HTTP call with timeout and user-friendly error handling.
  static Future<http.Response> _request(
    Future<http.Response> Function() call,
  ) async {
    try {
      return await call().timeout(_timeout);
    } on TimeoutException {
      throw ApiException('서버 응답 시간이 초과됐어요. 잠시 후 다시 시도해주세요');
    } on http.ClientException {
      throw ApiException('인터넷 연결을 확인해주세요');
    }
  }

  /// Maps HTTP error status codes to Korean messages.
  static Never _throwForStatus(http.Response response) {
    final detail = _parseDetail(response);
    switch (response.statusCode) {
      case 401:
        throw AuthException(detail ?? '로그인이 필요해요');
      case 403:
        throw ApiException(detail ?? '접근 권한이 없어요', statusCode: 403);
      case 404:
        throw ApiException(detail ?? '요청한 데이터를 찾을 수 없어요', statusCode: 404);
      case 429:
        throw ApiException(detail ?? '요청이 너무 많아요. 잠시 후 다시 시도해주세요', statusCode: 429);
      case >= 500:
        throw ApiException(detail ?? '서버에 문제가 생겼어요. 잠시 후 다시 시도해주세요', statusCode: response.statusCode);
      default:
        throw ApiException(detail ?? '요청에 실패했어요 (${response.statusCode})', statusCode: response.statusCode);
    }
  }

  // ─── Auth Token Management ───

  static String? _token;

  static Map<String, String> get _authHeaders => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  static Future<bool> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
    return _token != null;
  }

  static Future<void> _saveToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
  }

  static Future<void> clearToken() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
  }

  static bool get isLoggedIn => _token != null;

  /// Save a JWT received from OAuth redirect (public access for AuthGate).
  static Future<void> saveTokenDirect(String token) async {
    await _saveToken(token);
  }

  // ─── Auth API (static) ───

  static Future<void> login({
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      body: {'username': email, 'password': password},
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      await _saveToken(data['access_token'] as String);
    } else if (response.statusCode == 401) {
      throw AuthException('이메일 또는 비밀번호가 올바르지 않아요');
    } else {
      throw AuthException('로그인에 실패했어요. 다시 시도해주세요.');
    }
  }

  static Future<void> register({
    required String email,
    required String password,
    String? companyName,
  }) async {
    final body = <String, dynamic>{'email': email, 'password': password};
    if (companyName != null && companyName.isNotEmpty) {
      body['company_name'] = companyName;
    }

    final response = await http.post(
      Uri.parse('$baseUrl/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (response.statusCode == 200) {
      // Auto-login after registration
      await login(email: email, password: password);
    } else if (response.statusCode == 400) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      throw AuthException(data['detail'] ?? '이미 등록된 이메일이에요');
    } else {
      throw AuthException('회원가입에 실패했어요. 다시 시도해주세요.');
    }
  }

  static Future<void> socialLogin({
    required String provider,
    required String accessToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/social'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'provider': provider, 'access_token': accessToken}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      await _saveToken(data['access_token'] as String);
    } else {
      final detail = _parseDetail(response);
      throw AuthException(detail ?? '소셜 로그인에 실패했어요');
    }
  }

  static String? _parseDetail(http.Response response) {
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      return data['detail'] as String?;
    } catch (_) {
      return null;
    }
  }

  // ─── Public API (no auth required) ───

  Future<List<Notice>> fetchNotices({
    String? keyword,
    bool excludeClosed = false,
    int page = 1,
  }) async {
    final queryParams = <String, String>{};
    if (keyword != null && keyword.isNotEmpty) {
      queryParams['keyword'] = keyword;
    }
    queryParams['exclude_closed'] = excludeClosed.toString();
    queryParams['page'] = page.toString();
    queryParams['limit'] = '20';

    final uri = Uri.parse(
      '$baseUrl/bids/feed',
    ).replace(queryParameters: queryParams);
    final response = await _request(() => http.get(uri));

    if (response.statusCode == 200) {
      List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
      return body.map((dynamic item) => Notice.fromJson(item)).toList();
    }
    _throwForStatus(response);
  }

  Future<void> triggerCrawl() async {
    final response = await _request(
      () => http.post(Uri.parse('$baseUrl/bids/crawl')),
    );
    if (response.statusCode != 200) {
      _throwForStatus(response);
    }
  }

  Future<Map<String, dynamic>> calculateBidDetailed({
    required double basicPrice,
    required double rate,
    String? contractType,
    int? aValue,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/bids/calculate/detailed'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'basic_price': basicPrice,
          'rate': rate,
          'contract_type': contractType ?? 'CONSTRUCTION',
          'a_value': aValue ?? 0,
        }),
      ),
    );

    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    _throwForStatus(response);
  }

  Future<AiAnalysis> fetchBidAnalysis(
    String bidNo,
    Map<String, String> params,
  ) async {
    String url = '$baseUrl/ai/$bidNo/analysis';
    if (params.isNotEmpty) {
      url +=
          '?${params.entries.map((e) => '${e.key}=${Uri.encodeComponent(e.value)}').join('&')}';
    }

    final response = await _request(() => http.get(Uri.parse(url)));

    if (response.statusCode == 200) {
      return AiAnalysis.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
    }
    _throwForStatus(response);
  }

  Future<void> toggleFavorite(String bidNo) async {
    final response = await _request(
      () => http.post(Uri.parse('$baseUrl/bids/$bidNo/favorite')),
    );
    if (response.statusCode != 200) {
      _throwForStatus(response);
    }
  }

  Future<List<Notice>> fetchFavorites() async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/bids/favorites/list')),
    );
    if (response.statusCode == 200) {
      List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
      return body.map((dynamic item) => Notice.fromJson(item)).toList();
    }
    _throwForStatus(response);
  }

  Future<List<OpeningResult>> fetchOpeningResults(String bidNo) async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/bids/$bidNo/results')),
    );
    if (response.statusCode == 200) {
      List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
      return body
          .map((dynamic item) => OpeningResult.fromJson(item))
          .toList();
    }
    _throwForStatus(response);
  }

  // ─── Protected API (auth required) ───

  Future<User> getUserMe() async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/users/me'), headers: _authHeaders),
    );
    if (response.statusCode == 200) {
      return User.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<User> updateUserMe(Map<String, dynamic> data) async {
    final response = await _request(
      () => http.put(
        Uri.parse('$baseUrl/users/me'),
        headers: _authHeaders,
        body: jsonEncode(data),
      ),
    );
    if (response.statusCode == 200) {
      return User.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  // ─── Points API (auth required) ───

  Future<Map<String, dynamic>> getPointBalance() async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/points/balance'), headers: _authHeaders),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> deductPoints(String bidNo) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/points/deduct'),
        headers: _authHeaders,
        body: jsonEncode({'bid_no': bidNo}),
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    if (response.statusCode == 402) {
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      throw ApiException(body['detail'] ?? '포인트가 부족해요', statusCode: 402);
    }
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> getDailyFreeStatus() async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/points/daily-free'), headers: _authHeaders),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> createPaymentOrder(int amount) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/payments/create-order'),
        headers: _authHeaders,
        body: jsonEncode({'amount': amount}),
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> chargePoints(int amount) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/points/charge'),
        headers: _authHeaders,
        body: jsonEncode({'amount': amount}),
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<List<Map<String, dynamic>>> getPointHistory({int limit = 20}) async {
    final response = await _request(
      () => http.get(
        Uri.parse('$baseUrl/points/history?limit=$limit'),
        headers: _authHeaders,
      ),
    );
    if (response.statusCode == 200) {
      final List<dynamic> body = jsonDecode(utf8.decode(response.bodyBytes));
      return body.cast<Map<String, dynamic>>();
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> fetchScientificAnalysis(String bidNo) async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/prediction/$bidNo/recommend-points')),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    _throwForStatus(response);
  }

  // ─── Smart Bid API ───

  Future<CompetitionPrediction> predictCompetition({
    required String bidType,
    required double estimatedAmount,
    String agencyName = '',
    String? bidDate,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/smart-bid/competition/predict'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'bid_type': bidType,
          'estimated_amount': estimatedAmount,
          'agency_name': agencyName,
          if (bidDate != null) 'bid_date': bidDate,
        }),
      ),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      return CompetitionPrediction.fromJson(json['data']);
    }
    _throwForStatus(response);
  }

  Future<SmartBidRecommendation> getSmartRecommendation({
    required double baseAmount,
    String bidType = 'construction',
    double aValue = 0,
    double? estimatedAmount,
    String agencyName = '',
    String? bidDate,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/smart-bid/recommend'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'base_amount': baseAmount,
          'bid_type': bidType,
          'a_value': aValue,
          'agency_name': agencyName,
          if (estimatedAmount != null) 'estimated_amount': estimatedAmount,
          if (bidDate != null) 'bid_date': bidDate,
        }),
      ),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      return SmartBidRecommendation.fromJson(json['data']);
    }
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> predictBidRate({
    required String bidType,
    required double estimatedAmount,
    int expectedParticipants = 10,
    String agencyName = '',
    String? bidDate,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/smart-bid/rate/predict'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'bid_type': bidType,
          'estimated_amount': estimatedAmount,
          'expected_participants': expectedParticipants,
          'agency_name': agencyName,
          if (bidDate != null) 'bid_date': bidDate,
        }),
      ),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      return json['data'] as Map<String, dynamic>;
    }
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> verifyBid({
    required String bidNo,
    required double myBidPrice,
    required double basicPrice,
    String organization = '',
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/smart-bid/verify'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'bid_no': bidNo,
          'my_bid_price': myBidPrice,
          'basic_price': basicPrice,
          'organization': organization,
        }),
      ),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      return json['data'] as Map<String, dynamic>;
    }
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> fetchAgencyInsights({
    required String agencyName,
    String? bidType,
  }) async {
    final queryParams = {
      'agency_name': agencyName,
      if (bidType != null) 'bid_type': bidType,
    };
    final uri = Uri.parse(
      '$baseUrl/smart-bid/agency/insights',
    ).replace(queryParameters: queryParams);
    final response = await _request(() => http.get(uri));
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      return json['data'] as Map<String, dynamic>;
    }
    _throwForStatus(response);
  }

  Future<List<Map<String, dynamic>>> getAgencyStats({
    required String bidType,
    String keyword = '',
    int limit = 20,
  }) async {
    final queryParams = {
      'bid_type': bidType,
      'keyword': keyword,
      'limit': limit.toString(),
    };
    final uri = Uri.parse(
      '$baseUrl/smart-bid/agency/stats',
    ).replace(queryParameters: queryParams);
    final response = await _request(() => http.get(uri));
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      final List<dynamic> data = json['data'] ?? [];
      return data.cast<Map<String, dynamic>>();
    }
    _throwForStatus(response);
  }

  // ─── Deep Analysis API ───

  Future<DeepAnalysis> fetchDeepAnalysis(String bidId) async {
    final response = await _request(
      () => http.post(Uri.parse('$baseUrl/analysis/$bidId/deep')),
    );
    if (response.statusCode == 200) {
      return DeepAnalysis.fromJson(
          jsonDecode(utf8.decode(response.bodyBytes)));
    }
    _throwForStatus(response);
  }

  Future<List<Map<String, dynamic>>> fetchAttachments(String bidId) async {
    final response = await _request(
      () => http.get(Uri.parse('$baseUrl/analysis/$bidId/attachments')),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      final List<dynamic> data = json['attachments'] ?? [];
      return data.cast<Map<String, dynamic>>();
    }
    _throwForStatus(response);
  }

  // ─── Agency Profile API (auth required) ───

  Future<AgencyProfile> fetchAgencyProfile({
    required String organization,
    int months = 6,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/agency/profile'),
        headers: _authHeaders,
        body: jsonEncode({
          'organization': organization,
          'months': months,
        }),
      ),
    );
    if (response.statusCode == 200) {
      return AgencyProfile.fromJson(
          jsonDecode(utf8.decode(response.bodyBytes)));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  // ─── Subscription API ───

  Future<Map<String, dynamic>> createSubscriptionOrder({
    required String tier,
    required String billingCycle,
  }) async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/payments/subscribe'),
        headers: _authHeaders,
        body: jsonEncode({'tier': tier, 'billing_cycle': billingCycle}),
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> getSubscription() async {
    final response = await _request(
      () => http.get(
        Uri.parse('$baseUrl/payments/subscription'),
        headers: _authHeaders,
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<Map<String, dynamic>> cancelSubscription() async {
    final response = await _request(
      () => http.post(
        Uri.parse('$baseUrl/payments/subscribe/cancel'),
        headers: _authHeaders,
      ),
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    if (response.statusCode == 401) await clearToken();
    _throwForStatus(response);
  }

  Future<List<Map<String, dynamic>>> searchAgencies(
    String keyword, {
    int limit = 10,
  }) async {
    final queryParams = {
      'keyword': keyword,
      'limit': limit.toString(),
    };
    final uri = Uri.parse(
      '$baseUrl/smart-bid/agency/search',
    ).replace(queryParameters: queryParams);
    final response = await _request(() => http.get(uri));
    if (response.statusCode == 200) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      final List<dynamic> data = json['data'] ?? [];
      return data.cast<Map<String, dynamic>>();
    }
    _throwForStatus(response);
  }
}
