import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme/style.dart';
import '../services/api_service.dart';
import '../models/ai_analysis.dart';
import '../models/notice.dart';
import '../utils/snackbar_utils.dart';

class AiAnalysisCard extends StatefulWidget {
  final Notice notice;

  const AiAnalysisCard({
    super.key,
    required this.notice,
  });

  @override
  State<AiAnalysisCard> createState() => _AiAnalysisCardState();
}

class _AiAnalysisCardState extends State<AiAnalysisCard>
    with SingleTickerProviderStateMixin {
  final ApiService _apiService = ApiService();
  late Future<AiAnalysis> _analysisFuture;
  late AnimationController _animationController;
  late Animation<double> _fadeAnimation;
  late Animation<Offset> _slideAnimation;

  // 초보자 설명 토글 상태
  final Map<int, bool> _expandedTips = {};

  @override
  void initState() {
    super.initState();
    _loadAnalysis();

    _animationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    _fadeAnimation = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOut),
    );

    _slideAnimation = Tween<Offset>(
      begin: const Offset(0, 0.1),
      end: Offset.zero,
    ).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOut),
    );
  }

  void _loadAnalysis() {
    _analysisFuture = _apiService.fetchBidAnalysis(
      widget.notice.bidNo,
      widget.notice.toAnalysisParams(),
    );
  }

  void _retry() {
    setState(() {
      _loadAnalysis();
    });
  }

  @override
  void dispose() {
    _animationController.dispose();
    super.dispose();
  }

  Future<void> _launchURL() async {
    final Uri url = Uri.parse(widget.notice.content);
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        SnackBarUtils.showError(context, "원문 링크를 열 수 없어요");
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AiAnalysis>(
      future: _analysisFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return _buildLoadingState();
        } else if (snapshot.hasError) {
          return _buildErrorState();
        } else if (!snapshot.hasData) {
          return const SizedBox.shrink();
        }

        // 분석 완료 시 애니메이션 시작
        _animationController.forward();

        final data = snapshot.data!;
        return FadeTransition(
          opacity: _fadeAnimation,
          child: SlideTransition(
            position: _slideAnimation,
            child: _buildAnalysisContent(data),
          ),
        );
      },
    );
  }

  /// 로딩 상태 UI
  Widget _buildLoadingState() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          const SizedBox(
            width: 48,
            height: 48,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              valueColor: AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            "입찰 전략을 분석하고 있어요",
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppColors.textMain,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            "잠시만 기다려주세요...",
            style: TextStyle(
              fontSize: 13,
              color: AppColors.textSub.withOpacity(0.8),
            ),
          ),
          const SizedBox(height: 20),
          _buildSkeletonItem(),
          const SizedBox(height: 12),
          _buildSkeletonItem(widthFactor: 0.7),
          const SizedBox(height: 12),
          _buildSkeletonItem(widthFactor: 0.85),
        ],
      ),
    );
  }

  Widget _buildSkeletonItem({double widthFactor = 1.0}) {
    return Row(
      children: [
        Container(
          width: 20,
          height: 20,
          decoration: BoxDecoration(
            color: Colors.grey[200],
            borderRadius: BorderRadius.circular(10),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: widthFactor,
            child: Container(
              height: 14,
              decoration: BoxDecoration(
                color: Colors.grey[200],
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
        ),
      ],
    );
  }

  /// 에러 상태 UI
  Widget _buildErrorState() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.dangerRed.withOpacity(0.1),
              borderRadius: BorderRadius.circular(28),
            ),
            child: const Icon(
              Icons.wifi_off_rounded,
              color: AppColors.dangerRed,
              size: 28,
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            "분석을 불러오지 못했어요",
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppColors.textMain,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            "네트워크 연결을 확인해주세요",
            style: TextStyle(
              fontSize: 13,
              color: AppColors.textSub.withOpacity(0.8),
            ),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: _retry,
              icon: const Icon(Icons.refresh_rounded, size: 18),
              label: const Text("다시 시도"),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primaryBlue,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                elevation: 0,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 분석 결과 메인 콘텐츠
  Widget _buildAnalysisContent(AiAnalysis data) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 1. 헤더
          _buildHeader(data.sentiment),
          const SizedBox(height: 16),

          // 2. 공고 요약
          if (data.summary.isNotEmpty) ...[
            _buildSummarySection(data.summary),
            const SizedBox(height: 16),
          ],

          // 3. 마감/가격 정보 카드
          _buildQuickInfoCards(data),
          const SizedBox(height: 16),

          // 4. 참가 자격 요건
          if (data.eligibility.hasRestrictions) ...[
            _buildEligibilitySection(data.eligibility),
            const SizedBox(height: 16),
          ],

          // 5. 입찰 전략 팁 (메인 섹션)
          _buildTipsSection(data.sortedTips),
          const SizedBox(height: 20),

          // 6. 데이터 신뢰성 안내
          _buildDataSourceNote(),
          const SizedBox(height: 16),

          // 7. 액션 버튼
          _buildActionButtons(data),
        ],
      ),
    );
  }

  /// 헤더
  Widget _buildHeader(AnalysisSentiment sentiment) {
    final (statusText, statusColor, statusBgColor) = switch (sentiment) {
      AnalysisSentiment.safe => (
          "안전해요",
          AppColors.safeGreen,
          AppColors.safeGreen.withOpacity(0.1)
        ),
      AnalysisSentiment.caution => (
          "주의 필요",
          const Color(0xFFFF9500),
          const Color(0xFFFF9500).withOpacity(0.1)
        ),
      AnalysisSentiment.danger => (
          "위험해요",
          AppColors.dangerRed,
          AppColors.dangerRed.withOpacity(0.1)
        ),
    };

    return Row(
      children: [
        const Icon(Icons.auto_awesome, size: 20, color: AppColors.primaryBlue),
        const SizedBox(width: 8),
        const Text(
          "입찰 전략 분석",
          style: TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: AppColors.textMain,
          ),
        ),
        const Spacer(),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: statusBgColor,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                sentiment == AnalysisSentiment.safe
                    ? Icons.check_circle_rounded
                    : Icons.warning_rounded,
                size: 14,
                color: statusColor,
              ),
              const SizedBox(width: 4),
              Text(
                statusText,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: statusColor,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  /// 공고 요약
  Widget _buildSummarySection(String summary) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.primaryBlue.withOpacity(0.05),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        summary,
        style: const TextStyle(
          fontSize: 14,
          color: AppColors.textMain,
          height: 1.6,
        ),
      ),
    );
  }

  /// 빠른 정보 카드 (마감, 가격)
  Widget _buildQuickInfoCards(AiAnalysis data) {
    return Row(
      children: [
        // 마감 정보
        Expanded(
          child: _buildInfoCard(
            icon: data.deadlineInfo.isUrgent ? Icons.alarm : Icons.schedule,
            iconColor: data.deadlineInfo.isUrgent
                ? AppColors.dangerRed
                : AppColors.primaryBlue,
            title: "마감까지",
            value: data.deadlineInfo.daysRemaining != null
                ? "${data.deadlineInfo.daysRemaining}일"
                : "-",
            isHighlighted: data.deadlineInfo.isUrgent,
          ),
        ),
        const SizedBox(width: 12),
        // 가격 정보
        Expanded(
          child: _buildInfoCard(
            icon: Icons.payments_outlined,
            iconColor: AppColors.safeGreen,
            title: "기초금액",
            value: data.priceInfo.basicPriceFormatted ?? "-",
            isHighlighted: false,
          ),
        ),
      ],
    );
  }

  Widget _buildInfoCard({
    required IconData icon,
    required Color iconColor,
    required String title,
    required String value,
    required bool isHighlighted,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: isHighlighted
            ? AppColors.dangerRed.withOpacity(0.08)
            : Colors.grey[50],
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isHighlighted
              ? AppColors.dangerRed.withOpacity(0.3)
              : AppColors.divider,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: iconColor),
              const SizedBox(width: 6),
              Text(
                title,
                style: TextStyle(
                  fontSize: 12,
                  color: AppColors.textSub,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: isHighlighted ? AppColors.dangerRed : AppColors.textMain,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  /// 참가 자격 섹션
  Widget _buildEligibilitySection(EligibilityInfo eligibility) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF3E0),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFFFCC80)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.warning_amber_rounded,
                  size: 18, color: Color(0xFFE65100)),
              SizedBox(width: 8),
              Text(
                "참가 자격 확인 필요",
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                  color: Color(0xFFE65100),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ...eligibility.requirements.map((req) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text("• ",
                        style: TextStyle(color: Color(0xFFE65100))),
                    Expanded(
                      child: Text(
                        req,
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textMain,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  /// 입찰 전략 팁 섹션 (메인)
  Widget _buildTipsSection(List<BidTip> tips) {
    if (tips.isEmpty) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Text("💡", style: TextStyle(fontSize: 16)),
            SizedBox(width: 8),
            Text(
              "입찰 전략 팁",
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        ...tips
            .asMap()
            .entries
            .map((entry) => _buildTipCard(entry.key, entry.value)),
      ],
    );
  }

  /// 개별 팁 카드
  Widget _buildTipCard(int index, BidTip tip) {
    final isExpanded = _expandedTips[index] ?? false;
    final hasBeginnerExplanation =
        tip.forBeginners != null && tip.forBeginners!.isNotEmpty;

    Color importanceColor;
    switch (tip.importance) {
      case 'HIGH':
        importanceColor = AppColors.dangerRed;
        break;
      case 'MEDIUM':
        importanceColor = const Color(0xFFFF9500);
        break;
      default:
        importanceColor = AppColors.safeGreen;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          // 팁 메인 콘텐츠
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 헤더 (아이콘 + 제목 + 중요도)
                Row(
                  children: [
                    Text(tip.icon, style: const TextStyle(fontSize: 18)),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        tip.title,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textMain,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: importanceColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        tip.importance,
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: importanceColor,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                // 팁 내용
                Text(
                  tip.content,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.textMain,
                    height: 1.6,
                  ),
                ),
                const SizedBox(height: 8),
                // 데이터 출처
                Text(
                  "📊 ${tip.source}",
                  style: TextStyle(
                    fontSize: 11,
                    color: AppColors.textSub.withOpacity(0.7),
                  ),
                ),
              ],
            ),
          ),
          // 초보자 설명 토글
          if (hasBeginnerExplanation) ...[
            const Divider(height: 1),
            InkWell(
              onTap: () {
                setState(() {
                  _expandedTips[index] = !isExpanded;
                });
              },
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                child: Row(
                  children: [
                    Icon(
                      isExpanded ? Icons.school : Icons.school_outlined,
                      size: 16,
                      color: AppColors.primaryBlue,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      isExpanded ? "초보자 설명 접기" : "초보자를 위한 설명 보기",
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.primaryBlue,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const Spacer(),
                    Icon(
                      isExpanded ? Icons.expand_less : Icons.expand_more,
                      size: 18,
                      color: AppColors.primaryBlue,
                    ),
                  ],
                ),
              ),
            ),
            if (isExpanded) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppColors.primaryBlue.withOpacity(0.05),
                  borderRadius: const BorderRadius.only(
                    bottomLeft: Radius.circular(12),
                    bottomRight: Radius.circular(12),
                  ),
                ),
                child: Text(
                  tip.forBeginners!,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.textMain,
                    height: 1.6,
                  ),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }

  /// 데이터 신뢰성 안내
  Widget _buildDataSourceNote() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Icon(Icons.verified_outlined, size: 16, color: AppColors.textSub),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "모든 정보는 공공데이터포털 API 및 법률 기준에서 도출되었습니다.",
              style: TextStyle(
                fontSize: 11,
                color: AppColors.textSub,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 액션 버튼
  Widget _buildActionButtons(AiAnalysis analysis) {
    final hasAttachment = widget.notice.attachmentUrl != null &&
        widget.notice.attachmentUrl!.isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 투찰 계산하기 버튼 (메인 CTA)
        ElevatedButton.icon(
          onPressed: () {
            // A값 정보가 있으면 포함하여 전달
            Notice noticeToPass = widget.notice;

            if (analysis.aValueInfo != null && analysis.aValueInfo!.found) {
              noticeToPass = noticeToPass.copyWith(
                aValue: analysis.aValueInfo!.total,
                netCost: analysis.netCost,
              );
            }

            Navigator.pushNamed(
              context,
              '/calculator',
              arguments: noticeToPass,
            );
          },
          icon: const Icon(Icons.calculate_rounded, size: 20),
          label: const Text("투찰 계산하기"),
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.safeGreen,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(vertical: 16),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            elevation: 0,
          ),
        ),
        const SizedBox(height: 12),
        // 원문/규격서 버튼 Row
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _launchURL,
                icon: const Icon(Icons.description_outlined, size: 18),
                label: const Text("원문 보기"),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.textMain,
                  side: const BorderSide(color: AppColors.divider),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
              ),
            ),
            if (hasAttachment) ...[
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () async {
                    final Uri url = Uri.parse(widget.notice.attachmentUrl!);
                    if (!await launchUrl(url,
                        mode: LaunchMode.externalApplication)) {
                      if (mounted) {
                        SnackBarUtils.showError(context, "첨부파일을 열 수 없어요");
                      }
                    }
                  },
                  icon: const Icon(Icons.attachment_rounded, size: 18),
                  label: const Text("규격서"),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.textMain,
                    side: const BorderSide(color: AppColors.divider),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}
