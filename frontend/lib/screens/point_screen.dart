import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/api_service.dart';
import '../theme/style.dart';
import '../widgets/state_widgets.dart';
import '../utils/snackbar_utils.dart';

class PointScreen extends StatefulWidget {
  const PointScreen({super.key});

  @override
  State<PointScreen> createState() => _PointScreenState();
}

class _PointScreenState extends State<PointScreen> {
  final ApiService _apiService = ApiService();
  bool _isLoading = true;
  String? _error;
  int _points = 0;
  List<Map<String, dynamic>> _history = [];
  bool _isCharging = false;

  static const List<int> _chargeOptions = [5000, 10000, 30000, 50000];

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final results = await Future.wait([
        _apiService.getPointBalance(),
        _apiService.getPointHistory(limit: 50),
      ]);

      final balance = results[0] as Map<String, dynamic>;
      final history = results[1] as List<Map<String, dynamic>>;

      setState(() {
        _points = balance['points'] ?? 0;
        _history = history;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _chargePoints(int amount) async {
    HapticFeedback.mediumImpact();
    setState(() => _isCharging = true);

    try {
      final result = await _apiService.chargePoints(amount);
      setState(() {
        _points = result['remaining_points'] ?? _points;
        _isCharging = false;
      });

      if (mounted) {
        SnackBarUtils.showSuccess(context, result['message'] ?? '충전 완료');
      }
      // 내역 새로고침
      _loadData();
    } catch (e) {
      setState(() => _isCharging = false);
      if (mounted) {
        SnackBarUtils.showError(context, '충전에 실패했어요. 다시 시도해주세요');
      }
    }
  }

  void _showChargeSheet() {
    HapticFeedback.lightImpact();
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        padding: const EdgeInsets.all(24),
        decoration: const BoxDecoration(
          color: AppColors.surfaceWhite,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 핸들 바
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              "포인트 충전",
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              "투찰금액 복사 1회당 500원이 차감됩니다",
              style: TextStyle(fontSize: 14, color: AppColors.textSub),
            ),
            const SizedBox(height: 24),
            ..._chargeOptions.map((amount) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: SizedBox(
                    width: double.infinity,
                    child: OutlinedButton(
                      onPressed: _isCharging
                          ? null
                          : () {
                              Navigator.pop(context);
                              _chargePoints(amount);
                            },
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        side: const BorderSide(color: AppColors.divider),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            _formatNumber(amount),
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w700,
                              color: AppColors.textMain,
                            ),
                          ),
                          const Text(
                            "원",
                            style: TextStyle(
                              fontSize: 16,
                              color: AppColors.textSub,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            "(${amount ~/ 500}회 이용)",
                            style: const TextStyle(
                              fontSize: 14,
                              color: AppColors.primaryBlue,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                )),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  String _formatNumber(int number) {
    return number.toString().replaceAllMapped(
          RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
          (Match m) => '${m[1]},',
        );
  }

  String _txTypeLabel(String txType) {
    switch (txType) {
      case 'BID_COPY':
        return '투찰금액 복사';
      case 'CHARGE':
        return '포인트 충전';
      case 'SIGNUP_BONUS':
        return '가입 보너스';
      case 'AI_ANALYSIS':
        return 'AI 분석';
      default:
        return txType;
    }
  }

  IconData _txTypeIcon(String txType) {
    switch (txType) {
      case 'BID_COPY':
        return Icons.content_copy_rounded;
      case 'CHARGE':
        return Icons.add_circle_rounded;
      case 'SIGNUP_BONUS':
        return Icons.card_giftcard_rounded;
      case 'AI_ANALYSIS':
        return Icons.auto_awesome_rounded;
      default:
        return Icons.swap_horiz_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text("포인트"),
        backgroundColor: AppColors.surfaceWhite,
        foregroundColor: AppColors.textMain,
        elevation: 0,
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingStateWidget(
        message: "포인트 정보를 불러오는 중...",
        skeletonCount: 3,
      );
    }

    if (_error != null) {
      return ErrorStateWidget(
        title: "포인트 정보를 불러오지 못했어요",
        message: "네트워크 연결을 확인해주세요",
        onRetry: _loadData,
      );
    }

    return RefreshIndicator(
      onRefresh: _loadData,
      color: AppColors.primaryBlue,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: Column(
          children: [
            _buildBalanceCard(),
            const SizedBox(height: 12),
            _buildHistorySection(),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }

  Widget _buildBalanceCard() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      color: AppColors.surfaceWhite,
      child: Column(
        children: [
          const Text(
            "보유 포인트",
            style: TextStyle(fontSize: 14, color: AppColors.textSub),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                _formatNumber(_points),
                style: const TextStyle(
                  fontSize: 36,
                  fontWeight: FontWeight.w800,
                  color: AppColors.textMain,
                ),
              ),
              const SizedBox(width: 4),
              const Text(
                "P",
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  color: AppColors.primaryBlue,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            "투찰금액 복사 ${_points ~/ 500}회 가능",
            style: const TextStyle(fontSize: 13, color: AppColors.textSub),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _isCharging ? null : _showChargeSheet,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primaryBlue,
                foregroundColor: Colors.white,
                disabledBackgroundColor: AppColors.primaryBlue.withOpacity(0.5),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                elevation: 0,
              ),
              child: _isCharging
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text(
                      "충전하기",
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHistorySection() {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.03),
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
              Icon(Icons.history_rounded, size: 20, color: AppColors.primaryBlue),
              SizedBox(width: 8),
              Text(
                "이용 내역",
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textMain,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_history.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Center(
                child: Text(
                  "아직 이용 내역이 없어요",
                  style: TextStyle(fontSize: 14, color: AppColors.textSub),
                ),
              ),
            )
          else
            ..._history.map((tx) => _buildHistoryItem(tx)),
        ],
      ),
    );
  }

  Widget _buildHistoryItem(Map<String, dynamic> tx) {
    final int amount = tx['amount'] ?? 0;
    final String txType = tx['tx_type'] ?? '';
    final String? description = tx['description'];
    final String? createdAt = tx['created_at'];
    final bool isPositive = amount > 0;

    String dateStr = '';
    if (createdAt != null) {
      try {
        final dt = DateTime.parse(createdAt);
        dateStr = '${dt.month}/${dt.day} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
      } catch (_) {
        dateStr = createdAt;
      }
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: isPositive
                  ? AppColors.safeGreen.withOpacity(0.1)
                  : AppColors.dangerRed.withOpacity(0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              _txTypeIcon(txType),
              size: 18,
              color: isPositive ? AppColors.safeGreen : AppColors.dangerRed,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _txTypeLabel(txType),
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textMain,
                  ),
                ),
                if (description != null && description.isNotEmpty)
                  Text(
                    description,
                    style: const TextStyle(fontSize: 12, color: AppColors.textSub),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${isPositive ? "+" : ""}${_formatNumber(amount)}P',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: isPositive ? AppColors.safeGreen : AppColors.dangerRed,
                ),
              ),
              Text(
                dateStr,
                style: const TextStyle(fontSize: 11, color: AppColors.textSub),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
