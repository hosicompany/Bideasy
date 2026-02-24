import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:flutter/foundation.dart';

/// Centralized analytics service for BidEasy.
/// Wraps Firebase Analytics with graceful degradation.
class AnalyticsService {
  static final AnalyticsService _instance = AnalyticsService._();
  factory AnalyticsService() => _instance;
  AnalyticsService._();

  FirebaseAnalytics? _analytics;
  bool _initialized = false;

  /// Initialize after Firebase.initializeApp().
  void initialize() {
    if (_initialized) return;
    try {
      _analytics = FirebaseAnalytics.instance;
      _initialized = true;
    } catch (e) {
      debugPrint('[Analytics] Firebase Analytics not available: $e');
    }
  }

  // --- Screen Tracking ---
  Future<void> logScreenView(String screenName) async {
    await _analytics?.logScreenView(screenName: screenName);
  }

  // --- Feature Usage ---
  Future<void> logFeatureUsed(String feature, {Map<String, Object>? params}) async {
    await _analytics?.logEvent(
      name: 'feature_used',
      parameters: {'feature_name': feature, ...?params},
    );
  }

  // --- AI Analysis ---
  Future<void> logAiAnalysis(String bidNo, {String tier = 'free'}) async {
    await _analytics?.logEvent(
      name: 'ai_analysis_requested',
      parameters: {'bid_no': bidNo, 'user_tier': tier},
    );
  }

  // --- Calculator ---
  Future<void> logCalculatorUsed({
    required String safetyLevel,
    required double rate,
  }) async {
    await _analytics?.logEvent(
      name: 'calculator_used',
      parameters: {'rate': rate, 'safety_level': safetyLevel},
    );
  }

  // --- Bid Copy ---
  Future<void> logBidCopied({required String bidNo, required bool wasFree}) async {
    await _analytics?.logEvent(
      name: 'bid_copied',
      parameters: {'bid_no': bidNo, 'was_free': wasFree.toString()},
    );
  }

  // --- Subscription ---
  Future<void> logSubscriptionViewed() async {
    await _analytics?.logEvent(name: 'subscription_page_viewed');
  }

  Future<void> logSubscriptionStarted(String tier, String billingCycle) async {
    await _analytics?.logEvent(
      name: 'subscription_started',
      parameters: {'tier': tier, 'billing_cycle': billingCycle},
    );
  }

  // --- Payment ---
  Future<void> logPaymentStarted(int amount) async {
    await _analytics?.logEvent(
      name: 'payment_started',
      parameters: {'amount': amount},
    );
  }

  // --- Search ---
  Future<void> logSearch(String keyword) async {
    await _analytics?.logSearch(searchTerm: keyword);
  }

  // --- User Properties ---
  Future<void> setUserTier(String tier) async {
    await _analytics?.setUserProperty(name: 'user_tier', value: tier);
  }
}
