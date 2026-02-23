import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../utils/format_utils.dart';
import '../theme/style.dart';
import '../models/notice.dart';
import '../models/smart_bid.dart';
import '../services/api_service.dart';
import 'competition_badge.dart';
import 'glossary_chip.dart';

/// 스마트 투찰 추천 카드
class SmartBidCard extends StatefulWidget {
  final Notice notice;
  final ValueChanged<double>? onApplyRate;

  const SmartBidCard({
    super.key,
    required this.notice,
    this.onApplyRate,
  });

  @override
  State<SmartBidCard> createState() => _SmartBidCardState();
}

class _SmartBidCardState extends State<SmartBidCard>
    with SingleTickerProviderStateMixin {
  final ApiService _apiService = ApiService();

  CompetitionPrediction? _competition;
  SmartBidRecommendation? _recommendation;
  bool _isLoading = true;
  String? _error;

  late AnimationController _animationController;
  late Animation<double> _fadeAnimation;
  late Animation<Offset> _slideAnimation;

  @override
  void initState() {
    super.initState();
    _animationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _fadeAnimation = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOut),
    );
    _slideAnimation =
        Tween<Offset>(begin: const Offset(0, 0.1), end: Offset.zero).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOut),
    );
    _fetchData();
  }

  @override
  void dispose() {
    _animationController.dispose();
    super.dispose();
  }

  Future<void> _fetchData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final bidType = normalizeBidType(widget.notice.bidType);
      final results = await Future.wait([
        _apiService.predictCompetition(
          bidType: bidType,
          estimatedAmount: widget.notice.basicPrice,
          agencyName: widget.notice.organization ?? '',
        ),
        _apiService.getSmartRecommendation(
          baseAmount: widget.notice.basicPrice,
          bidType: bidType,
          aValue: (widget.notice.aValue ?? 0).toDouble(),
          agencyName: widget.notice.organization ?? '',
        ),
      ]);

      if (mounted) {
        setState(() {
          _competition = results[0] as CompetitionPrediction;
          _recommendation = results[1] as SmartBidRecommendation;
          _isLoading = false;
        });
        _animationController.forward();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) return _buildLoading();
    if (_error != null) return _buildError();
    return FadeTransition(
      opacity: _fadeAnimation,
      child: SlideTransition(
        position: _slideAnimation,
        child: _buildContent(),
      ),
    );
  }

  Widget _buildLoading() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: _cardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildSkeletonRow(0.5),
          const SizedBox(height: 16),
          _buildSkeletonRow(1.0, height: 12),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: _buildSkeletonBox()),
              const SizedBox(width: 12),
              Expanded(child: _buildSkeletonBox()),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _buildSkeletonBox()),
              const SizedBox(width: 12),
              Expanded(child: _buildSkeletonBox()),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSkeletonRow(double widthFactor, {double height = 16}) {
    return FractionallySizedBox(
      widthFactor: widthFactor,
      alignment: Alignment.centerLeft,
      child: Container(
        height: height,
        decoration: BoxDecoration(
          color: Colors.grey[200],
          borderRadius: BorderRadius.circular(4),
        ),
      ),
    );
  }

  Widget _buildSkeletonBox() {
    return Container(
      height: 60,
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(12),
      ),
    );
  }

  Widget _buildError() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: _cardDecoration(),
      child: Column(
        children: [
          Icon(Icons.cloud_off_rounded, color: Colors.grey[400], size: 32),
          const SizedBox(height: 8),
          Text(
            'AI 분석을 불러올 수 없습니다',
            style: AppTextStyles.caption.copyWith(color: Colors.grey[500]),
          ),
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: _fetchData,
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('다시 시도'),
            style: TextButton.styleFrom(foregroundColor: AppColors.primaryBlue),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final comp = _competition!;
    final rec = _recommendation!;
    final level = comp.level;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: _cardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              const Text(
                '✨ 스마트 투찰 추천',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textMain,
                  fontFamily: 'Pretendard',
                ),
              ),
              const Spacer(),
              CompetitionBadge(level: level, compact: false),
            ],
          ),
          const SizedBox(height: 20),

          // Competition Gauge
          _buildCompetitionGauge(comp.predictedCount, level),
          const SizedBox(height: 20),

          // Info Grid (2x2)
          Row(
            children: [
              Expanded(
                child: _buildInfoTile(
                  icon: Icons.payments_outlined,
                  label: '최적 투찰가',
                  value: _formatPrice(rec.optimalBid),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildInfoTile(
                  icon: Icons.percent_rounded,
                  label: '투찰률',
                  value: '${rec.effectiveRate.toStringAsFixed(3)}%',
                  glossaryTerm: '투찰률',
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _buildInfoTile(
                  icon: Icons.shield_outlined,
                  label: '낙찰하한률',
                  value: rec.lowerLimitPct,
                  glossaryTerm: '낙찰하한율',
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildInfoTile(
                  icon: Icons.tune_rounded,
                  label: '적용 마진',
                  value: '+${rec.appliedMarginPct.toStringAsFixed(2)}%',
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // Recommendation message
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: level.color.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('💡 ', style: TextStyle(fontSize: 14, height: 1.4)),
                Expanded(
                  child: Text(
                    rec.recommendation.isNotEmpty
                        ? rec.recommendation
                        : comp.strategy,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.textMain,
                      height: 1.4,
                      fontFamily: 'Pretendard',
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Apply button
          if (widget.onApplyRate != null)
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () {
                  HapticFeedback.mediumImpact();
                  // Convert effective rate to slider offset from 100%
                  // Slider rate = effective_rate - 100 (e.g. 87.755% → -12.245%)
                  final sliderRate = rec.effectiveRate - 100.0;
                  widget.onApplyRate!(sliderRate);
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryBlue,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  elevation: 0,
                ),
                child: const Text(
                  '이 가격으로 적용하기',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    fontFamily: 'Pretendard',
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 경쟁도 게이지 (그라데이션 바 + 마커)
  Widget _buildCompetitionGauge(int count, CompetitionLevel level) {
    // Normalize position (non-linear scale)
    double normalized;
    if (count <= 5) {
      normalized = count / 50.0; // 0-10%
    } else if (count <= 10) {
      normalized = 0.1 + (count - 5) / 25.0; // 10-30%
    } else if (count <= 20) {
      normalized = 0.3 + (count - 10) / 40.0; // 30-55%
    } else if (count <= 50) {
      normalized = 0.55 + (count - 20) / 120.0; // 55-80%
    } else {
      normalized = 0.8 + ((count - 50).clamp(0, 50)) / 250.0; // 80-100%
    }
    normalized = normalized.clamp(0.02, 0.98);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '예상 참여 업체수',
          style: AppTextStyles.caption,
        ),
        const SizedBox(height: 8),
        LayoutBuilder(
          builder: (context, constraints) {
            final markerLeft = normalized * constraints.maxWidth;
            return Column(
              children: [
                Stack(
                  clipBehavior: Clip.none,
                  children: [
                    // Gradient bar
                    Container(
                      height: 12,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(6),
                        gradient: const LinearGradient(
                          colors: [
                            Color(0xFF3182F6),
                            Color(0xFF34C759),
                            Color(0xFFFFCC00),
                            Color(0xFFFF9500),
                            Color(0xFFFF3B30),
                          ],
                          stops: [0.0, 0.2, 0.4, 0.65, 1.0],
                        ),
                      ),
                    ),
                    // Marker
                    Positioned(
                      left: markerLeft - 6,
                      top: -4,
                      child: Container(
                        width: 12,
                        height: 20,
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(
                            color: level.color,
                            width: 2.5,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: 0.15),
                              blurRadius: 4,
                              offset: const Offset(0, 1),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                // Labels
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('1명', style: TextStyle(fontSize: 10, color: Colors.grey[400])),
                    Text('51+명', style: TextStyle(fontSize: 10, color: Colors.grey[400])),
                  ],
                ),
              ],
            );
          },
        ),
        const SizedBox(height: 8),
        RichText(
          text: TextSpan(
            children: [
              TextSpan(
                text: '$count개사',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: level.color,
                  fontFamily: 'Pretendard',
                ),
              ),
              const TextSpan(
                text: ' 참여 예상',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w500,
                  color: AppColors.textSub,
                  fontFamily: 'Pretendard',
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildInfoTile({
    required IconData icon,
    required String label,
    required String value,
    String? glossaryTerm,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8F9FA),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 14, color: AppColors.textSub),
              const SizedBox(width: 4),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textSub,
                  fontFamily: 'Pretendard',
                ),
              ),
              if (glossaryTerm != null) GlossaryChip(term: glossaryTerm),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.textMain,
              fontFamily: 'Pretendard',
            ),
          ),
        ],
      ),
    );
  }

  BoxDecoration _cardDecoration() {
    return BoxDecoration(
      color: AppColors.surfaceWhite,
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: AppColors.divider),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.04),
          blurRadius: 8,
          offset: const Offset(0, 2),
        ),
      ],
    );
  }

  String _formatPrice(double price) => formatPriceKorean(price);
}
