import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_service.dart';
import '../services/toss_payments.dart';
import '../theme/style.dart';
import '../utils/snackbar_utils.dart';
import '../providers/api_service_provider.dart';

class SubscriptionScreen extends ConsumerStatefulWidget {
  const SubscriptionScreen({super.key});

  @override
  ConsumerState<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends ConsumerState<SubscriptionScreen> {
  bool _isLoading = true;
  bool _isProcessing = false;
  String _currentTier = 'free';
  String? _expiresAt;
  bool _isAnnual = false;

  @override
  void initState() {
    super.initState();
    _loadSubscription();
  }

  Future<void> _loadSubscription() async {
    try {
      final api = ref.read(apiServiceProvider);
      final sub = await api.getSubscription();
      if (mounted) {
        setState(() {
          _currentTier = sub['tier'] ?? 'free';
          _expiresAt = sub['expires_at'];
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _subscribe(String tier) async {
    HapticFeedback.mediumImpact();
    setState(() => _isProcessing = true);

    try {
      final api = ref.read(apiServiceProvider);
      final order = await api.createSubscriptionOrder(
        tier: tier,
        billingCycle: _isAnnual ? 'annual' : 'monthly',
      );

      final backendBase = ApiService.baseUrl;
      final successUrl = '$backendBase/payments/subscribe/success';
      final failUrl = '$backendBase/payments/fail';

      await requestTossPayment(
        clientKey: order['toss_client_key'],
        orderId: order['order_id'],
        amount: order['amount'],
        orderName: order['order_name'],
        customerName: order['customer_name'],
        successUrl: successUrl,
        failUrl: failUrl,
      );
    } catch (e) {
      setState(() => _isProcessing = false);
      if (mounted) {
        SnackBarUtils.showError(context, '결제를 시작할 수 없어요. 다시 시도해주세요');
      }
    }
  }

  String _formatNumber(int number) {
    return number.toString().replaceAllMapped(
          RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
          (Match m) => '${m[1]},',
        );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text("구독 관리"),
        backgroundColor: AppColors.surfaceWhite,
        foregroundColor: AppColors.textMain,
        elevation: 0,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: AppColors.primaryBlue))
          : SingleChildScrollView(
              child: Column(
                children: [
                  _buildCurrentStatus(),
                  const SizedBox(height: 12),
                  _buildBillingToggle(),
                  const SizedBox(height: 12),
                  _buildTierCard(
                    tier: 'free',
                    name: 'Free',
                    price: 0,
                    color: AppColors.textSub,
                    features: [
                      '공고 피드 조회',
                      '투찰가 계산기',
                      'AI 분석 (일 1회)',
                    ],
                    locked: [
                      '첨부파일 심층 분석',
                      '경쟁 강도 예측',
                      '투찰가 검증',
                      '기관 프로파일링',
                      '스마트 추천',
                    ],
                  ),
                  _buildTierCard(
                    tier: 'pro',
                    name: 'Pro',
                    price: _isAnnual ? 12400 : 14900,
                    color: AppColors.primaryBlue,
                    features: [
                      '공고 피드 조회',
                      '투찰가 계산기',
                      'AI 분석 (무제한)',
                      '첨부파일 심층 분석',
                      '경쟁 강도 예측',
                      '투찰가 검증',
                    ],
                    locked: [
                      '기관 프로파일링',
                      '스마트 추천',
                      '사정률 예측',
                    ],
                    isPopular: true,
                  ),
                  _buildTierCard(
                    tier: 'pro_plus',
                    name: 'Pro+',
                    price: _isAnnual ? 24900 : 29900,
                    color: const Color(0xFFE65100),
                    features: [
                      '공고 피드 조회',
                      '투찰가 계산기',
                      'AI 분석 (무제한)',
                      '첨부파일 심층 분석',
                      '경쟁 강도 예측',
                      '투찰가 검증',
                      '기관 프로파일링',
                      '스마트 추천',
                      '사정률 예측',
                    ],
                    locked: [],
                  ),
                  const SizedBox(height: 32),
                ],
              ),
            ),
    );
  }

  Widget _buildCurrentStatus() {
    final isSubscribed = _currentTier != 'free';
    final tierLabel = _currentTier == 'pro_plus' ? 'Pro+' : _currentTier == 'pro' ? 'Pro' : 'Free';

    String expiryText = '';
    if (_expiresAt != null && isSubscribed) {
      try {
        final dt = DateTime.parse(_expiresAt!);
        expiryText = '${dt.year}.${dt.month.toString().padLeft(2, '0')}.${dt.day.toString().padLeft(2, '0')}까지';
      } catch (_) {}
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      color: AppColors.surfaceWhite,
      child: Column(
        children: [
          Text(
            '현재 플랜',
            style: TextStyle(fontSize: 14, color: AppColors.textSub),
          ),
          const SizedBox(height: 8),
          Text(
            tierLabel,
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w800,
              color: isSubscribed ? AppColors.primaryBlue : AppColors.textMain,
            ),
          ),
          if (expiryText.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(expiryText, style: TextStyle(fontSize: 13, color: AppColors.textSub)),
          ],
        ],
      ),
    );
  }

  Widget _buildBillingToggle() {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Expanded(
            child: GestureDetector(
              onTap: () {
                HapticFeedback.lightImpact();
                setState(() => _isAnnual = false);
              },
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: !_isAnnual ? AppColors.primaryBlue : Colors.transparent,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Center(
                  child: Text(
                    '월간',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: !_isAnnual ? Colors.white : AppColors.textSub,
                    ),
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            child: GestureDetector(
              onTap: () {
                HapticFeedback.lightImpact();
                setState(() => _isAnnual = true);
              },
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: _isAnnual ? AppColors.primaryBlue : Colors.transparent,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Center(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '연간',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: _isAnnual ? Colors.white : AppColors.textSub,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: _isAnnual ? Colors.white.withValues(alpha: 0.2) : AppColors.safeGreen.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          '2개월 무료',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: _isAnnual ? Colors.white : AppColors.safeGreen,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTierCard({
    required String tier,
    required String name,
    required int price,
    required Color color,
    required List<String> features,
    required List<String> locked,
    bool isPopular = false,
  }) {
    final isCurrent = _currentTier == tier;
    final isFree = tier == 'free';

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: isPopular
            ? Border.all(color: AppColors.primaryBlue, width: 2)
            : Border.all(color: AppColors.divider),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 10,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        children: [
          if (isPopular)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(
                color: AppColors.primaryBlue,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
              ),
              child: const Center(
                child: Text(
                  '가장 인기',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Colors.white),
                ),
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      name,
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        color: color,
                      ),
                    ),
                    if (isCurrent) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: color.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          '현재',
                          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 8),
                if (isFree)
                  const Text(
                    '무료',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.textMain),
                  )
                else
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Text(
                        '${_formatNumber(price)}원',
                        style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.textMain),
                      ),
                      const Text(
                        '/월',
                        style: TextStyle(fontSize: 14, color: AppColors.textSub),
                      ),
                    ],
                  ),
                if (_isAnnual && !isFree) ...[
                  const SizedBox(height: 4),
                  Text(
                    '연 ${_formatNumber(price * 10)}원 결제',
                    style: TextStyle(fontSize: 12, color: AppColors.textSub),
                  ),
                ],
                const SizedBox(height: 16),
                ...features.map((f) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          Icon(Icons.check_circle_rounded, size: 18, color: color),
                          const SizedBox(width: 8),
                          Text(f, style: const TextStyle(fontSize: 14, color: AppColors.textMain)),
                        ],
                      ),
                    )),
                ...locked.map((f) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          Icon(Icons.lock_rounded, size: 18, color: AppColors.textSub.withValues(alpha: 0.5)),
                          const SizedBox(width: 8),
                          Text(
                            f,
                            style: TextStyle(fontSize: 14, color: AppColors.textSub.withValues(alpha: 0.5)),
                          ),
                        ],
                      ),
                    )),
                if (!isFree && !isCurrent) ...[
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: _isProcessing ? null : () => _subscribe(tier),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: color,
                        foregroundColor: Colors.white,
                        disabledBackgroundColor: color.withValues(alpha: 0.5),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        elevation: 0,
                      ),
                      child: _isProcessing
                          ? const SizedBox(
                              width: 20, height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : Text(
                              '$name 구독하기',
                              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                            ),
                    ),
                  ),
                ],
                if (isCurrent && !isFree) ...[
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton(
                      onPressed: _isProcessing ? null : _showCancelDialog,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.dangerRed,
                        side: const BorderSide(color: AppColors.dangerRed),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      child: const Text(
                        '구독 해지',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _showCancelDialog() {
    HapticFeedback.mediumImpact();
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('구독 해지', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
        content: const Text(
          '구독을 해지하시겠어요?\n만료일까지 계속 이용 가능합니다.',
          style: TextStyle(fontSize: 15),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소', style: TextStyle(color: AppColors.textSub)),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _cancelSubscription();
            },
            child: const Text('해지하기', style: TextStyle(color: AppColors.dangerRed)),
          ),
        ],
      ),
    );
  }

  Future<void> _cancelSubscription() async {
    setState(() => _isProcessing = true);
    try {
      final api = ref.read(apiServiceProvider);
      final result = await api.cancelSubscription();
      if (mounted) {
        SnackBarUtils.showSuccess(context, result['message'] ?? '구독이 해지되었어요');
        _loadSubscription();
      }
    } catch (e) {
      if (mounted) {
        SnackBarUtils.showError(context, '구독 해지에 실패했어요');
      }
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }
}
