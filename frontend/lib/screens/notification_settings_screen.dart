import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../theme/style.dart';

class NotificationSettingsScreen extends StatefulWidget {
  const NotificationSettingsScreen({super.key});

  @override
  State<NotificationSettingsScreen> createState() =>
      _NotificationSettingsScreenState();
}

class _NotificationSettingsScreenState
    extends State<NotificationSettingsScreen> {
  bool _newBid = true;
  bool _favoriteUpdate = true;
  bool _subscriptionExpiry = true;
  bool _isLoading = true;

  static const _keyNewBid = 'noti_new_bid';
  static const _keyFavoriteUpdate = 'noti_favorite_update';
  static const _keySubscriptionExpiry = 'noti_subscription_expiry';

  @override
  void initState() {
    super.initState();
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _newBid = prefs.getBool(_keyNewBid) ?? true;
      _favoriteUpdate = prefs.getBool(_keyFavoriteUpdate) ?? true;
      _subscriptionExpiry = prefs.getBool(_keySubscriptionExpiry) ?? true;
      _isLoading = false;
    });
  }

  Future<void> _savePreference(String key, bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(key, value);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text('알림 설정'),
        backgroundColor: AppColors.surfaceWhite,
        foregroundColor: AppColors.textMain,
        elevation: 0,
      ),
      body: _isLoading
          ? const Center(
              child: CircularProgressIndicator(
                valueColor:
                    AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
              ),
            )
          : ListView(
              children: [
                const SizedBox(height: 12),
                Container(
                  margin: const EdgeInsets.symmetric(horizontal: 20),
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: AppColors.surfaceWhite,
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.03),
                        blurRadius: 10,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.notifications_outlined,
                              size: 20, color: AppColors.primaryBlue),
                          SizedBox(width: 8),
                          Text(
                            '푸시 알림',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: AppColors.textMain,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '알림을 받을 항목을 선택해주세요',
                        style: AppTextStyles.caption
                            .copyWith(color: AppColors.textSub),
                      ),
                      const SizedBox(height: 20),
                      _buildToggle(
                        icon: Icons.description_outlined,
                        title: '새 공고 알림',
                        subtitle: '내 조건에 맞는 새 공고가 등록되면 알려드려요',
                        value: _newBid,
                        onChanged: (val) {
                          HapticFeedback.lightImpact();
                          setState(() => _newBid = val);
                          _savePreference(_keyNewBid, val);
                        },
                      ),
                      const Divider(height: 24, color: AppColors.divider),
                      _buildToggle(
                        icon: Icons.star_outline_rounded,
                        title: '즐겨찾기 변동',
                        subtitle: '즐겨찾기한 공고의 상태가 변경되면 알려드려요',
                        value: _favoriteUpdate,
                        onChanged: (val) {
                          HapticFeedback.lightImpact();
                          setState(() => _favoriteUpdate = val);
                          _savePreference(_keyFavoriteUpdate, val);
                        },
                      ),
                      const Divider(height: 24, color: AppColors.divider),
                      _buildToggle(
                        icon: Icons.card_membership_outlined,
                        title: '구독 만료 알림',
                        subtitle: '구독 만료 3일 전에 알려드려요',
                        value: _subscriptionExpiry,
                        onChanged: (val) {
                          HapticFeedback.lightImpact();
                          setState(() => _subscriptionExpiry = val);
                          _savePreference(_keySubscriptionExpiry, val);
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 36),
                  child: Text(
                    '알림 설정은 이 기기에만 적용됩니다.\n기기의 알림 권한이 꺼져 있으면 알림을 받을 수 없어요.',
                    style: TextStyle(
                      fontSize: 12,
                      color: AppColors.textSub.withValues(alpha: 0.7),
                      height: 1.5,
                    ),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _buildToggle({
    required IconData icon,
    required String title,
    required String subtitle,
    required bool value,
    required ValueChanged<bool> onChanged,
  }) {
    return Row(
      children: [
        Icon(icon, size: 20, color: AppColors.textSub),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w500,
                  color: AppColors.textMain,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: AppTextStyles.caption.copyWith(
                  color: AppColors.textSub,
                ),
              ),
            ],
          ),
        ),
        Switch.adaptive(
          value: value,
          onChanged: onChanged,
          activeTrackColor: AppColors.primaryBlue,
        ),
      ],
    );
  }
}
