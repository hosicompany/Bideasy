import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/style.dart';
import '../providers/notification_provider.dart';

class NotificationScreen extends ConsumerStatefulWidget {
  const NotificationScreen({super.key});

  @override
  ConsumerState<NotificationScreen> createState() => _NotificationScreenState();
}

class _NotificationScreenState extends ConsumerState<NotificationScreen> {
  @override
  void initState() {
    super.initState();
    Future(() => ref.read(notificationProvider.notifier).fetchNotifications());
  }

  String _formatTime(String isoString) {
    if (isoString.isEmpty) return '';
    try {
      final dt = DateTime.parse(isoString);
      final now = DateTime.now();
      final diff = now.difference(dt);

      if (diff.inMinutes < 1) return '방금 전';
      if (diff.inMinutes < 60) return '${diff.inMinutes}분 전';
      if (diff.inHours < 24) return '${diff.inHours}시간 전';
      if (diff.inDays < 7) return '${diff.inDays}일 전';
      return '${dt.month}/${dt.day}';
    } catch (_) {
      return '';
    }
  }

  IconData _iconForType(String notiType) {
    switch (notiType) {
      case 'new_bid':
        return Icons.description_outlined;
      case 'favorite_update':
        return Icons.star_outline_rounded;
      case 'subscription':
        return Icons.card_membership_outlined;
      case 'payment':
        return Icons.payment_outlined;
      default:
        return Icons.notifications_outlined;
    }
  }

  Color _colorForType(String notiType) {
    switch (notiType) {
      case 'new_bid':
        return AppColors.primaryBlue;
      case 'favorite_update':
        return AppColors.starGold;
      case 'subscription':
        return AppColors.safeGreen;
      case 'payment':
        return AppColors.warningOrange;
      default:
        return AppColors.textSub;
    }
  }

  @override
  Widget build(BuildContext context) {
    final notiState = ref.watch(notificationProvider);

    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text('알림'),
        actions: [
          if (notiState.unreadCount > 0)
            TextButton(
              onPressed: () {
                HapticFeedback.lightImpact();
                ref.read(notificationProvider.notifier).markAllAsRead();
              },
              child: const Text(
                '모두 읽음',
                style: TextStyle(
                  color: AppColors.primaryBlue,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
        ],
      ),
      body: notiState.isLoading
          ? const Center(
              child: CircularProgressIndicator(
                valueColor:
                    AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
              ),
            )
          : notiState.notifications.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.notifications_off_outlined,
                          size: 64, color: Colors.grey[300]),
                      const SizedBox(height: 16),
                      Text(
                        '아직 알림이 없어요',
                        style: AppTextStyles.body1
                            .copyWith(color: AppColors.textSub),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '새 공고나 중요한 소식이 있으면\n여기서 알려드릴게요',
                        textAlign: TextAlign.center,
                        style: AppTextStyles.caption
                            .copyWith(color: AppColors.textSub),
                      ),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: () =>
                      ref.read(notificationProvider.notifier).fetchNotifications(),
                  color: AppColors.primaryBlue,
                  child: ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    itemCount: notiState.notifications.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 1, color: AppColors.divider),
                    itemBuilder: (context, index) {
                      final noti = notiState.notifications[index];
                      return _NotificationTile(
                        noti: noti,
                        icon: _iconForType(noti.notiType),
                        iconColor: _colorForType(noti.notiType),
                        timeText: _formatTime(noti.createdAt),
                        onTap: () {
                          HapticFeedback.lightImpact();
                          if (!noti.isRead) {
                            ref
                                .read(notificationProvider.notifier)
                                .markAsRead(noti.id);
                          }
                        },
                      );
                    },
                  ),
                ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  final NotificationItem noti;
  final IconData icon;
  final Color iconColor;
  final String timeText;
  final VoidCallback onTap;

  const _NotificationTile({
    required this.noti,
    required this.icon,
    required this.iconColor,
    required this.timeText,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Container(
        color: noti.isRead ? AppColors.surfaceWhite : const Color(0xFFF0F6FF),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: iconColor.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: iconColor, size: 20),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    noti.title,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight:
                          noti.isRead ? FontWeight.w400 : FontWeight.w600,
                      color: AppColors.textMain,
                      fontFamily: 'Pretendard',
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    noti.body,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.caption.copyWith(
                      color: AppColors.textSub,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    timeText,
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.grey[400],
                      fontFamily: 'Pretendard',
                    ),
                  ),
                ],
              ),
            ),
            if (!noti.isRead)
              Container(
                width: 8,
                height: 8,
                margin: const EdgeInsets.only(top: 6, left: 8),
                decoration: const BoxDecoration(
                  color: AppColors.primaryBlue,
                  shape: BoxShape.circle,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
