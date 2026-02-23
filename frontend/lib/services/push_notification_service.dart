import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'api_service.dart';

/// Handles Firebase Cloud Messaging initialization and token registration.
///
/// Gracefully degrades when Firebase is not configured (no google-services.json
/// or GoogleService-Info.plist), so development builds work without Firebase.
class PushNotificationService {
  static final PushNotificationService _instance = PushNotificationService._();
  factory PushNotificationService() => _instance;
  PushNotificationService._();

  final _api = ApiService();
  bool _initialized = false;

  /// Initialize Firebase and request notification permissions.
  /// Call this after user authentication succeeds.
  Future<void> initialize() async {
    if (_initialized) return;

    try {
      await Firebase.initializeApp();
    } catch (e) {
      // Firebase not configured (no google-services.json / GoogleService-Info.plist)
      debugPrint('[FCM] Firebase not configured, skipping push notifications: $e');
      return;
    }

    final messaging = FirebaseMessaging.instance;

    // Request permission (iOS requires explicit permission, Android auto-grants)
    final settings = await messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    if (settings.authorizationStatus == AuthorizationStatus.denied) {
      debugPrint('[FCM] Notification permission denied');
      return;
    }

    // Get and register FCM token
    final token = await messaging.getToken();
    if (token != null) {
      await _registerToken(token);
    }

    // Listen for token refresh
    messaging.onTokenRefresh.listen(_registerToken);

    // Handle foreground messages
    FirebaseMessaging.onMessage.listen(_handleForegroundMessage);

    // Handle background/terminated message taps
    FirebaseMessaging.onMessageOpenedApp.listen(_handleMessageTap);

    // Check if app was opened from a terminated-state notification
    final initialMessage = await messaging.getInitialMessage();
    if (initialMessage != null) {
      _handleMessageTap(initialMessage);
    }

    _initialized = true;
    debugPrint('[FCM] Push notifications initialized');
  }

  Future<void> _registerToken(String token) async {
    String deviceType;
    if (kIsWeb) {
      deviceType = 'web';
    } else if (Platform.isAndroid) {
      deviceType = 'android';
    } else if (Platform.isIOS) {
      deviceType = 'ios';
    } else {
      deviceType = 'web';
    }

    try {
      await _api.registerDeviceToken(token, deviceType);
      debugPrint('[FCM] Token registered: ${token.substring(0, 20)}...');
    } catch (e) {
      debugPrint('[FCM] Failed to register token: $e');
    }
  }

  void _handleForegroundMessage(RemoteMessage message) {
    debugPrint('[FCM] Foreground message: ${message.notification?.title}');
    // Foreground notifications are handled by the system notification tray
    // on Android 13+ and iOS. No additional local notification display needed
    // for basic use cases.
  }

  void _handleMessageTap(RemoteMessage message) {
    debugPrint('[FCM] Message tapped: ${message.data}');
    // Navigate based on notification type
    final notiType = message.data['noti_type'];
    final bidNo = message.data['bid_no'];

    if (notiType == 'new_bid' && bidNo != null) {
      // Could navigate to bid detail — handled by the app's navigation layer
      debugPrint('[FCM] Should navigate to bid: $bidNo');
    }
  }

  /// Unregister token on logout.
  Future<void> unregister() async {
    if (!_initialized) return;

    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) {
        String deviceType;
        if (kIsWeb) {
          deviceType = 'web';
        } else if (Platform.isAndroid) {
          deviceType = 'android';
        } else if (Platform.isIOS) {
          deviceType = 'ios';
        } else {
          deviceType = 'web';
        }
        await _api.unregisterDeviceToken(token, deviceType);
      }
    } catch (e) {
      debugPrint('[FCM] Failed to unregister token: $e');
    }
  }
}
