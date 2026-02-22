import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../models/smart_bid.dart';

/// 경쟁 강도 시각 게이지 — 5단계 컬러 바 + 블루오션 확률 바
class CompetitionGauge extends StatelessWidget {
  final int predictedCount;
  final CompetitionLevel level;
  final double? blueOceanProb;

  const CompetitionGauge({
    super.key,
    required this.predictedCount,
    required this.level,
    this.blueOceanProb,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Main gauge
        _buildMainGauge(),
        const SizedBox(height: 16),
        // Blue ocean probability bar
        if (blueOceanProb != null) _buildBlueOceanBar(),
      ],
    );
  }

  Widget _buildMainGauge() {
    // Non-linear scale for gauge position
    double normalized;
    if (predictedCount <= 5) {
      normalized = predictedCount / 50.0;
    } else if (predictedCount <= 10) {
      normalized = 0.1 + (predictedCount - 5) / 25.0;
    } else if (predictedCount <= 20) {
      normalized = 0.3 + (predictedCount - 10) / 40.0;
    } else if (predictedCount <= 50) {
      normalized = 0.55 + (predictedCount - 20) / 120.0;
    } else {
      normalized = 0.8 + ((predictedCount - 50).clamp(0, 50)) / 250.0;
    }
    normalized = normalized.clamp(0.02, 0.98);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Count + level label
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              '$predictedCount개사',
              style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w700,
                color: level.color,
                fontFamily: 'Pretendard',
              ),
            ),
            const SizedBox(width: 8),
            const Text(
              '참여 예상',
              style: TextStyle(
                fontSize: 14,
                color: AppColors.textSub,
                fontFamily: 'Pretendard',
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        // Gradient gauge bar
        LayoutBuilder(
          builder: (context, constraints) {
            final markerLeft = normalized * constraints.maxWidth;
            return Column(
              children: [
                Stack(
                  clipBehavior: Clip.none,
                  children: [
                    // 5-segment gradient bar
                    Container(
                      height: 10,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(5),
                        gradient: const LinearGradient(
                          colors: [
                            Color(0xFF3182F6), // blueOcean
                            Color(0xFF34C759), // adequate
                            Color(0xFFFFCC00), // moderate
                            Color(0xFFFF9500), // competitive
                            Color(0xFFFF3B30), // redOcean
                          ],
                          stops: [0.0, 0.2, 0.4, 0.65, 1.0],
                        ),
                      ),
                    ),
                    // Marker thumb
                    Positioned(
                      left: markerLeft - 7,
                      top: -5,
                      child: Container(
                        width: 14,
                        height: 20,
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: level.color, width: 2.5),
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
                // Segment labels
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    _segmentLabel('🔵 1~5', CompetitionLevel.blueOcean),
                    _segmentLabel('🟢 6~10', CompetitionLevel.adequate),
                    _segmentLabel('🟡 11~20', CompetitionLevel.moderate),
                    _segmentLabel('🟠 21~50', CompetitionLevel.competitive),
                    _segmentLabel('🔴 51+', CompetitionLevel.redOcean),
                  ],
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  Widget _segmentLabel(String text, CompetitionLevel segment) {
    final isActive = segment == level;
    return Text(
      text,
      style: TextStyle(
        fontSize: 9,
        fontWeight: isActive ? FontWeight.w700 : FontWeight.w400,
        color: isActive ? level.color : Colors.grey[400],
        fontFamily: 'Pretendard',
      ),
    );
  }

  Widget _buildBlueOceanBar() {
    final prob = blueOceanProb!;
    final percent = (prob * 100).round();

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.primaryBlue.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                '🔵 블루오션 확률',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.textMain,
                  fontFamily: 'Pretendard',
                ),
              ),
              const Spacer(),
              Text(
                '$percent%',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: percent >= 50
                      ? AppColors.primaryBlue
                      : AppColors.textSub,
                  fontFamily: 'Pretendard',
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // Progress bar
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: prob.clamp(0.0, 1.0),
              minHeight: 6,
              backgroundColor: Colors.grey[200],
              valueColor: AlwaysStoppedAnimation<Color>(
                percent >= 50
                    ? AppColors.primaryBlue
                    : AppColors.textSub.withValues(alpha: 0.5),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
