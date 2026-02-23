import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_service.dart';
import 'api_service_provider.dart';

class NotificationItem {
  final int id;
  final String title;
  final String body;
  final String notiType;
  final Map<String, dynamic>? dataJson;
  final bool isRead;
  final String createdAt;

  const NotificationItem({
    required this.id,
    required this.title,
    required this.body,
    required this.notiType,
    this.dataJson,
    required this.isRead,
    required this.createdAt,
  });

  factory NotificationItem.fromJson(Map<String, dynamic> json) {
    return NotificationItem(
      id: json['id'] as int,
      title: json['title'] as String,
      body: json['body'] as String,
      notiType: json['noti_type'] as String,
      dataJson: json['data_json'] as Map<String, dynamic>?,
      isRead: json['is_read'] as bool,
      createdAt: json['created_at'] as String,
    );
  }
}

class NotificationState {
  final List<NotificationItem> notifications;
  final int unreadCount;
  final bool isLoading;

  const NotificationState({
    this.notifications = const [],
    this.unreadCount = 0,
    this.isLoading = false,
  });

  NotificationState copyWith({
    List<NotificationItem>? notifications,
    int? unreadCount,
    bool? isLoading,
  }) {
    return NotificationState(
      notifications: notifications ?? this.notifications,
      unreadCount: unreadCount ?? this.unreadCount,
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

class NotificationNotifier extends StateNotifier<NotificationState> {
  final ApiService _api;

  NotificationNotifier(this._api) : super(const NotificationState());

  Future<void> fetchUnreadCount() async {
    try {
      final count = await _api.getUnreadNotificationCount();
      state = state.copyWith(unreadCount: count);
    } catch (_) {
      // Silently fail — badge just won't update
    }
  }

  Future<void> fetchNotifications() async {
    state = state.copyWith(isLoading: true);
    try {
      final data = await _api.getNotifications();
      final items = data.map((e) => NotificationItem.fromJson(e)).toList();
      final unread = items.where((n) => !n.isRead).length;
      state = state.copyWith(
        notifications: items,
        unreadCount: unread,
        isLoading: false,
      );
    } catch (_) {
      state = state.copyWith(isLoading: false);
    }
  }

  Future<void> markAsRead(int notificationId) async {
    try {
      await _api.markNotificationRead(notificationId);
      final updated = state.notifications.map((n) {
        if (n.id == notificationId) {
          return NotificationItem(
            id: n.id,
            title: n.title,
            body: n.body,
            notiType: n.notiType,
            dataJson: n.dataJson,
            isRead: true,
            createdAt: n.createdAt,
          );
        }
        return n;
      }).toList();
      final unread = updated.where((n) => !n.isRead).length;
      state = state.copyWith(notifications: updated, unreadCount: unread);
    } catch (_) {}
  }

  Future<void> markAllAsRead() async {
    try {
      await _api.markAllNotificationsRead();
      final updated = state.notifications.map((n) {
        return NotificationItem(
          id: n.id,
          title: n.title,
          body: n.body,
          notiType: n.notiType,
          dataJson: n.dataJson,
          isRead: true,
          createdAt: n.createdAt,
        );
      }).toList();
      state = state.copyWith(notifications: updated, unreadCount: 0);
    } catch (_) {}
  }
}

final notificationProvider =
    StateNotifierProvider<NotificationNotifier, NotificationState>((ref) {
  final api = ref.watch(apiServiceProvider);
  return NotificationNotifier(api);
});
