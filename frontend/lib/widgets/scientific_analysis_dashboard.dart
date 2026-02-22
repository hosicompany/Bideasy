import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../models/notice.dart';
import '../models/smart_bid.dart';
import '../services/api_service.dart';
import 'competition_gauge.dart';
import 'glossary_chip.dart';

class ScientificAnalysisDashboard extends StatefulWidget {
  final String bidNo;
  final Notice? notice;

  const ScientificAnalysisDashboard({
    super.key,
    required this.bidNo,
    this.notice,
  });

  @override
  State<ScientificAnalysisDashboard> createState() =>
      _ScientificAnalysisDashboardState();
}

class _ScientificAnalysisDashboardState
    extends State<ScientificAnalysisDashboard> {
  final ApiService _apiService = ApiService();
  Map<String, dynamic>? _analysisData;
  CompetitionPrediction? _competition;
  Map<String, dynamic>? _bidRateData;
  Map<String, dynamic>? _agencyInsights;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchAnalysis();
  }

  Future<void> _fetchAnalysis() async {
    try {
      // 기존 API + ML API 병렬 호출
      final futures = <Future>[
        _apiService.fetchScientificAnalysis(widget.bidNo),
      ];

      // Notice가 있으면 ML API도 호출
      if (widget.notice != null) {
        final bidType = normalizeBidType(widget.notice!.bidType);
        final agencyName = widget.notice!.organization ?? '';
        futures.add(_apiService.predictCompetition(
          bidType: bidType,
          estimatedAmount: widget.notice!.basicPrice,
          agencyName: agencyName,
        ));
        futures.add(_apiService.predictBidRate(
          bidType: bidType,
          estimatedAmount: widget.notice!.basicPrice,
          agencyName: agencyName,
        ));
        if (agencyName.isNotEmpty) {
          futures.add(_apiService.fetchAgencyInsights(
            agencyName: agencyName,
            bidType: bidType,
          ));
        }
      }

      final results = await Future.wait(
        futures,
        eagerError: false,
      );

      if (mounted) {
        setState(() {
          _analysisData = results[0] as Map<String, dynamic>;
          if (results.length > 1 && results[1] is CompetitionPrediction) {
            _competition = results[1] as CompetitionPrediction;
          }
          if (results.length > 2 && results[2] is Map<String, dynamic>) {
            _bidRateData = results[2] as Map<String, dynamic>;
          }
          if (results.length > 3 && results[3] is Map<String, dynamic>) {
            _agencyInsights = results[3] as Map<String, dynamic>;
          }
          _isLoading = false;
        });
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
    if (_isLoading) {
      return const Padding(
        padding: EdgeInsets.all(32),
        child: Center(
          child: CircularProgressIndicator(color: AppColors.primaryBlue),
        ),
      );
    }

    if (_error != null) {
      return _buildErrorCard();
    }

    if (_analysisData == null) {
      return const SizedBox();
    }

    final agency = _analysisData!['agency_profile'] ?? {};
    final monteCarlo = _analysisData!['monte_carlo'] ?? {};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSection(
          icon: Icons.business_rounded,
          title: '발주처 성향 분석',
          child: _agencyInsights != null && _agencyInsights!['found'] == true
              ? _buildAgencyInsightsCard(_agencyInsights!)
              : _buildAgencyCard(agency),
        ),
        const SizedBox(height: 16),
        _buildSection(
          icon: Icons.casino_rounded,
          title: '몬테카를로 시뮬레이션',
          child: _buildMonteCarloCard(monteCarlo),
        ),
        const SizedBox(height: 16),
        _buildSection(
          icon: Icons.groups_rounded,
          title: '경쟁도 분석 (ML)',
          child: _buildMLCompetitionCard(),
        ),
        if (_bidRateData != null) ...[
          const SizedBox(height: 16),
          _buildSection(
            icon: Icons.trending_up_rounded,
            title: '낙찰률 예측 (ML)',
            child: _buildBidRateCard(),
          ),
        ],
      ],
    );
  }

  Widget _buildErrorCard() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: _cardDecoration(),
      child: Column(
        children: [
          Icon(Icons.analytics_outlined, color: Colors.grey[400], size: 32),
          const SizedBox(height: 8),
          Text(
            '과학적 분석을 불러올 수 없습니다',
            style: AppTextStyles.caption.copyWith(color: Colors.grey[500]),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: () {
              setState(() {
                _isLoading = true;
                _error = null;
              });
              _fetchAnalysis();
            },
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('다시 시도'),
          ),
        ],
      ),
    );
  }

  Widget _buildSection({
    required IconData icon,
    required String title,
    required Widget child,
  }) {
    return Container(
      decoration: _cardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
            child: Row(
              children: [
                Icon(icon, size: 18, color: AppColors.primaryBlue),
                const SizedBox(width: 8),
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textMain,
                    fontFamily: 'Pretendard',
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1, color: AppColors.divider),
          Padding(
            padding: const EdgeInsets.all(16),
            child: child,
          ),
        ],
      ),
    );
  }

  Widget _buildAgencyCard(Map data) {
    if (data['message'] != null) {
      return Text(
        data['message'],
        style: AppTextStyles.caption,
      );
    }
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  Text('과거 낙찰 평균 사정률', style: AppTextStyles.caption),
                  GlossaryChip(term: '사정률'),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                '${data['avg_rate']}%',
                style: const TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textMain,
                  fontFamily: 'Pretendard',
                ),
              ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.backgroundGrey,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            '표본 ${data['sample_size']}건',
            style: AppTextStyles.caption,
          ),
        ),
      ],
    );
  }

  Widget _buildAgencyInsightsCard(Map<String, dynamic> data) {
    final avgRate = (data['avg_rate'] as num?)?.toDouble() ?? 0;
    final medianRate = (data['median_rate'] as num?)?.toDouble() ?? 0;
    final minRate = (data['min_rate'] as num?)?.toDouble() ?? 0;
    final maxRate = (data['max_rate'] as num?)?.toDouble() ?? 0;
    final totalBids = data['total_bids'] as int? ?? 0;
    final avgParticipants = data['avg_participants'];
    final recent6m = data['recent_6m_count'] as int? ?? 0;
    final trend = data['rate_trend'] as String? ?? 'stable';
    final diffFromGlobal = (data['diff_from_global'] as num?)?.toDouble() ?? 0;
    final insight = data['insight'] as String? ?? '';

    IconData trendIcon;
    Color trendColor;
    String trendLabel;
    switch (trend) {
      case 'rising':
        trendIcon = Icons.trending_up_rounded;
        trendColor = AppColors.safeGreen;
        trendLabel = '상승';
      case 'falling':
        trendIcon = Icons.trending_down_rounded;
        trendColor = AppColors.dangerRed;
        trendLabel = '하락';
      default:
        trendIcon = Icons.trending_flat_rounded;
        trendColor = AppColors.textSub;
        trendLabel = '안정';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Row 1: avg rate + trend + participants
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('평균 낙찰률', style: AppTextStyles.caption),
                      GlossaryChip(term: '낙찰률'),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        '$avgRate%',
                        style: const TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textMain,
                          fontFamily: 'Pretendard',
                        ),
                      ),
                      const SizedBox(width: 6),
                      Icon(trendIcon, size: 20, color: trendColor),
                      Text(
                        trendLabel,
                        style: TextStyle(
                          fontSize: 12,
                          color: trendColor,
                          fontWeight: FontWeight.w600,
                          fontFamily: 'Pretendard',
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            if (avgParticipants != null)
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text('참여 중앙값', style: AppTextStyles.caption),
                  const SizedBox(height: 4),
                  Text(
                    '${(avgParticipants as num).toInt()}개사',
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textMain,
                      fontFamily: 'Pretendard',
                    ),
                  ),
                ],
              ),
          ],
        ),
        const SizedBox(height: 16),
        // Row 2: stat chips
        Row(
          children: [
            _buildStatChip('최근 6개월', '$recent6m건'),
            const SizedBox(width: 8),
            _buildStatChip('총 건수', '$totalBids건'),
            const SizedBox(width: 8),
            _buildStatChip(
              '낙찰 범위',
              '${minRate.toStringAsFixed(0)}~${maxRate.toStringAsFixed(0)}%',
            ),
          ],
        ),
        const SizedBox(height: 12),
        // Rate gauge (median position within min-max range)
        _buildRangeGauge(minRate, maxRate, medianRate, avgRate),
        // Insight comment
        if (insight.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: diffFromGlobal > 0
                  ? AppColors.safeGreen.withValues(alpha: 0.06)
                  : diffFromGlobal < -1
                      ? AppColors.dangerRed.withValues(alpha: 0.06)
                      : AppColors.backgroundGrey,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('💡 ', style: TextStyle(fontSize: 14)),
                Expanded(
                  child: Text(
                    insight,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.textMain,
                      fontFamily: 'Pretendard',
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildStatChip(String label, String value) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.backgroundGrey,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.textSub,
                fontFamily: 'Pretendard',
              ),
            ),
            const SizedBox(height: 2),
            Text(
              value,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
                fontFamily: 'Pretendard',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRangeGauge(
    double min, double max, double median, double avg,
  ) {
    if (max <= min) return const SizedBox();
    final range = max - min;
    final avgPos = ((avg - min) / range).clamp(0.0, 1.0);

    return Column(
      children: [
        Stack(
          children: [
            Container(
              height: 6,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [
                    AppColors.dangerRed,
                    AppColors.competitionYellow,
                    AppColors.safeGreen,
                  ],
                ),
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            Positioned(
              left: avgPos * (MediaQuery.of(context).size.width - 112) - 4,
              top: -3,
              child: Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: AppColors.primaryBlue,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 2),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.15),
                      blurRadius: 3,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              '${min.toStringAsFixed(1)}%',
              style: TextStyle(fontSize: 10, color: Colors.grey[400]),
            ),
            Text(
              '평균 ${avg.toStringAsFixed(1)}%',
              style: const TextStyle(
                fontSize: 10,
                color: AppColors.primaryBlue,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              '${max.toStringAsFixed(1)}%',
              style: TextStyle(fontSize: 10, color: Colors.grey[400]),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildMonteCarloCard(Map data) {
    final topRates = data['top_rates'] as List? ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          data['description'] ?? '가상 투찰 시뮬레이션 결과',
          style: AppTextStyles.caption,
        ),
        const SizedBox(height: 10),
        if (topRates.isNotEmpty)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: topRates
                .map((rate) => Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: AppColors.primaryBlue.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '${(rate as num).toStringAsFixed(3)}%',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.primaryBlue,
                          fontFamily: 'Pretendard',
                        ),
                      ),
                    ))
                .toList(),
          )
        else
          const Text('시뮬레이션 데이터 없음', style: AppTextStyles.caption),
      ],
    );
  }

  Widget _buildMLCompetitionCard() {
    if (_competition == null) {
      // Fallback to legacy data
      final legacy = _analysisData?['competition'] ?? {};
      if (legacy.isEmpty) {
        return const Text('경쟁도 데이터 없음', style: AppTextStyles.caption);
      }
      return _buildLegacyCompetitionCard(legacy);
    }

    final comp = _competition!;
    final level = comp.level;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Visual gauge replaces the old text-only display
        CompetitionGauge(
          predictedCount: comp.predictedCount,
          level: level,
          blueOceanProb: comp.blueOceanProbability,
        ),
        if (comp.strategy.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: level.color.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              comp.strategy,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.textMain,
                fontFamily: 'Pretendard',
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildLegacyCompetitionCard(Map data) {
    final count = data['predicted_count'] ?? 0;
    final difficulty = data['difficulty'] ?? 'MEDIUM';
    final message = data['message'] ?? '';

    Color color;
    if (difficulty == 'HIGH') {
      color = AppColors.competitionRed;
    } else if (difficulty == 'LOW') {
      color = AppColors.competitionBlue;
    } else {
      color = AppColors.competitionOrange;
    }

    return Column(
      children: [
        Text(
          '$count개사 참여 예상',
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: color,
            fontFamily: 'Pretendard',
          ),
        ),
        if (message.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(message, style: AppTextStyles.caption),
        ],
      ],
    );
  }

  Widget _buildBidRateCard() {
    final data = _bidRateData!;
    final predictedRate = (data['predicted_rate'] ?? 0).toDouble();
    final confidence = data['range'] as Map<String, dynamic>?;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('예상 낙찰률', style: AppTextStyles.caption),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              '${predictedRate.toStringAsFixed(2)}%',
              style: const TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
                fontFamily: 'Pretendard',
              ),
            ),
            if (confidence != null) ...[
              const SizedBox(width: 12),
              Text(
                '(${(confidence['lower'] as num).toStringAsFixed(1)}% ~ ${(confidence['upper'] as num).toStringAsFixed(1)}%)',
                style: AppTextStyles.caption,
              ),
            ],
          ],
        ),
        const SizedBox(height: 12),
        // 시각적 게이지 (80% ~ 100% 범위)
        _buildRateGauge(predictedRate),
      ],
    );
  }

  Widget _buildRateGauge(double rate) {
    // Display range: 80% to 100%
    final normalized = ((rate - 80) / 20).clamp(0.0, 1.0);

    return Column(
      children: [
        Stack(
          children: [
            Container(
              height: 8,
              decoration: BoxDecoration(
                color: AppColors.backgroundGrey,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
            FractionallySizedBox(
              widthFactor: normalized,
              child: Container(
                height: 8,
                decoration: BoxDecoration(
                  color: AppColors.primaryBlue,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('80%',
                style: TextStyle(fontSize: 10, color: Colors.grey[400])),
            Text('100%',
                style: TextStyle(fontSize: 10, color: Colors.grey[400])),
          ],
        ),
      ],
    );
  }

  BoxDecoration _cardDecoration() {
    return BoxDecoration(
      color: AppColors.surfaceWhite,
      borderRadius: BorderRadius.circular(16),
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
}
