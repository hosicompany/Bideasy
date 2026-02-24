import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import '../utils/format_utils.dart';
import '../theme/style.dart';
import '../models/notice.dart';
import '../widgets/ai_analysis_card.dart';
import '../widgets/scientific_analysis_dashboard.dart';
import '../widgets/opening_result_table.dart';
import '../widgets/smart_bid_card.dart';
import '../widgets/bid_verify_card.dart';
import '../widgets/glossary_chip.dart';
import '../widgets/deep_analysis_card.dart';
import '../widgets/agency_profile_sheet.dart';
import '../services/api_service.dart';
import '../utils/snackbar_utils.dart';
import '../services/analytics_service.dart';

/// 공고 상세 화면 (통합)
/// - 개찰 완료: 낙찰 결과 표시
/// - 진행 중: 투찰가 계산기
class BidCalculatorScreen extends StatefulWidget {
  final Notice notice;

  const BidCalculatorScreen({super.key, required this.notice});

  @override
  State<BidCalculatorScreen> createState() => _BidCalculatorScreenState();
}

class _BidCalculatorScreenState extends State<BidCalculatorScreen> {
  final ApiService _apiService = ApiService();
  double _rate = -5.0; // 사정률 (기본값 -5%)

  // A값 (고정비용)
  int _aValue = 0;
  bool _aValueApplied = false;

  // 순공사원가 (투찰 하한선 방어용)
  int _netCost = 0;
  bool _netCostApplied = false;

  // 일일 무료 복사
  bool _hasFreeToday = false;

  @override
  void initState() {
    super.initState();
    if (widget.notice.aValue != null && widget.notice.aValue! > 0) {
      _aValue = widget.notice.aValue!;
      _aValueApplied = true;
    }
    if (widget.notice.netCost != null && widget.notice.netCost! > 0) {
      _netCost = widget.notice.netCost!;
      _netCostApplied = true;
    }
    _loadFreeStatus();
  }

  Future<void> _loadFreeStatus() async {
    try {
      final status = await _apiService.getDailyFreeStatus();
      if (mounted) setState(() => _hasFreeToday = status['available'] ?? false);
    } catch (_) {
      // Silently fail - default to paid mode
    }
  }

  /// 스마트 투찰 추천 적용 (슬라이더 사정률 업데이트)
  void _applySmartRate(double rate) {
    setState(() {
      _rate = rate.clamp(-15.0, 5.0);
    });
    HapticFeedback.mediumImpact();
  }

  // 법정 낙찰하한율 (공사: 87.745%)
  static const double _lowerLimitRate = 87.745;

  double get _minRate => _lowerLimitRate - 100;

  double get _minSafeRate {
    if (!_netCostApplied || _netCost <= 0) return -15.0;
    double variablePart = _basicPrice;
    double target = _netCost.toDouble();
    if (_aValueApplied) {
      variablePart = _basicPrice - _aValue;
      target = target - _aValue;
    }
    if (variablePart <= 0) return -15.0;
    final safeRate = ((target / variablePart) - 1) * 100;
    return safeRate + 0.1;
  }

  double get _basicPrice => widget.notice.basicPrice;
  double get _estimatedMin => _basicPrice * 0.97;
  double get _estimatedMax => _basicPrice * 1.03;

  int get _bidPrice {
    double target;
    if (_aValueApplied) {
      final variablePart = _basicPrice - _aValue;
      target = (variablePart * (1 + _rate / 100)) + _aValue;
    } else {
      target = _basicPrice * (1 + _rate / 100);
    }
    return (target ~/ 10) * 10;
  }

  int get _lowerLimitPrice {
    final target = _basicPrice * (_lowerLimitRate / 100);
    return (target ~/ 10) * 10;
  }

  double get _distanceFromLimit {
    if (_lowerLimitPrice == 0) return 100.0;
    return ((_bidPrice - _lowerLimitPrice) / _lowerLimitPrice) * 100;
  }

  bool get _isBelowNetCost => _netCostApplied && _bidPrice < _netCost;

  String get _safetyLevel {
    if (_isBelowNetCost) return "DANGER";
    if (_bidPrice < _lowerLimitPrice) return "DANGER";
    if (_bidPrice < _lowerLimitPrice * 1.02) return "WARNING";
    return "SAFE";
  }

  bool get _isDanger => _safetyLevel == "DANGER";
  bool get _isWarning => _safetyLevel == "WARNING";
  bool get _isClosed => widget.notice.isClosed;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _isClosed
          ? AppColors.backgroundGrey
          : (_isDanger ? const Color(0xFFFFEBEE) : AppColors.backgroundGrey),
      appBar: AppBar(
        title: Text(_isClosed ? "낙찰 결과" : "투찰가 계산"),
        backgroundColor: _isClosed
            ? AppColors.primaryBlue
            : (_isDanger ? AppColors.dangerRed : AppColors.surfaceWhite),
        foregroundColor: _isClosed
            ? Colors.white
            : (_isDanger ? Colors.white : AppColors.textMain),
        elevation: 0,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // 공고 정보 카드 (공통)
              _buildNoticeInfoCard(),
              const SizedBox(height: 20),

              // 분기: 개찰 완료 vs 진행 중
              if (_isClosed) ...[
                _buildClosedContent(),
              ] else ...[
                _buildActiveContent(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  /// 개찰 완료 컨텐츠
  Widget _buildClosedContent() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 낙찰 결과 헤더
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                AppColors.primaryBlue,
                AppColors.primaryBlue.withValues(alpha:0.8),
              ],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: AppColors.primaryBlue.withValues(alpha:0.3),
                blurRadius: 12,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            children: [
              const Icon(Icons.emoji_events_rounded,
                  color: Colors.amber, size: 48),
              const SizedBox(height: 12),
              const Text(
                "개찰 완료",
                style: TextStyle(
                  fontSize: 14,
                  color: Colors.white70,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                "기초금액: ${_formatPriceKorean(_basicPrice)}",
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              if (widget.notice.openingDate != null) ...[
                const SizedBox(height: 8),
                Text(
                  "개찰일: ${DateFormat('yyyy.MM.dd HH:mm').format(widget.notice.openingDate!)}",
                  style: const TextStyle(
                    fontSize: 13,
                    color: Colors.white70,
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 24),

        // 개찰 순위 테이블
        OpeningResultTable(notice: widget.notice),
        const SizedBox(height: 24),

        // 역검증 카드
        BidVerifyCard(notice: widget.notice),
        const SizedBox(height: 24),

        // AI 분석 (참고용)
        const Text(
          "📊 공고 분석",
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: AppColors.textMain,
          ),
        ),
        const SizedBox(height: 12),
        AiAnalysisCard(notice: widget.notice),
        const SizedBox(height: 24),

        // 첨부파일 심층 분석
        DeepAnalysisCard(bidNo: widget.notice.bidNo),
        const SizedBox(height: 24),

        // 과학적 분석
        const Text(
          "🧪 과학적 분석 (Scientific Bidding)",
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: Colors.indigo,
          ),
        ),
        const SizedBox(height: 12),
        ScientificAnalysisDashboard(bidNo: widget.notice.bidNo, notice: widget.notice),
      ],
    );
  }

  /// 진행 중 컨텐츠 (기존 투찰 계산기)
  Widget _buildActiveContent() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 가격 정보 카드
        _buildPriceInfoCard(),
        const SizedBox(height: 20),

        // 슬라이더 섹션
        _buildSliderSection(),
        const SizedBox(height: 20),

        // 결과 카드
        _buildResultCard(),
        const SizedBox(height: 24),

        // 스마트 투찰 추천
        SmartBidCard(
          notice: widget.notice,
          onApplyRate: (rate) => _applySmartRate(rate),
        ),
        const SizedBox(height: 24),

        // AI 분석
        AiAnalysisCard(notice: widget.notice),
        const SizedBox(height: 24),

        // 첨부파일 심층 분석
        DeepAnalysisCard(bidNo: widget.notice.bidNo),
        const SizedBox(height: 24),

        // 과학적 분석
        const Text(
          "🧪 과학적 분석 (Scientific Bidding)",
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: Colors.indigo,
          ),
        ),
        const SizedBox(height: 12),
        ScientificAnalysisDashboard(bidNo: widget.notice.bidNo, notice: widget.notice),
        const SizedBox(height: 40),

        // 액션 버튼
        _buildActionButtons(),
      ],
    );
  }

  /// 공고 정보 카드
  Widget _buildNoticeInfoCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 상태 배지
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: _isClosed
                  ? AppColors.primaryBlue.withValues(alpha:0.1)
                  : AppColors.safeGreen.withValues(alpha:0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              _isClosed ? "개찰 완료" : "입찰 진행중",
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: _isClosed ? AppColors.primaryBlue : AppColors.safeGreen,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            widget.notice.title,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppColors.textMain,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 8),
          GestureDetector(
            onTap: () {
              final org = widget.notice.organization;
              if (org != null && org.isNotEmpty) {
                AgencyProfileSheet.show(context, org);
              }
            },
            child: Text(
              widget.notice.organization ?? "발주처 미상",
              style: TextStyle(
                fontSize: 13,
                color: AppColors.textSub,
                decoration: widget.notice.organization != null
                    ? TextDecoration.underline
                    : null,
                decorationColor: AppColors.textSub,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 가격 정보 카드
  Widget _buildPriceInfoCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          _buildPriceRow("기초금액", _formatPriceKorean(_basicPrice), isBold: true, glossaryTerm: '기초금액'),
          const Divider(height: 20),
          _buildPriceRow("예정가격 범위",
              "${_formatPriceKorean(_estimatedMin)} ~ ${_formatPriceKorean(_estimatedMax)}",
              glossaryTerm: '예정가격'),
          const SizedBox(height: 8),
          _buildPriceRow("낙찰하한선 ($_lowerLimitRate%)",
              _formatPriceKorean(_lowerLimitPrice.toDouble()),
              highlight: true, glossaryTerm: '낙찰하한율'),
          if (_netCostApplied) ...[
            const SizedBox(height: 8),
            _buildPriceRow(
              "순공사원가 (투찰불가)",
              _formatPriceKorean(_netCost.toDouble()),
              highlight: true,
              glossaryTerm: '순공사원가',
            ),
          ],
          if (_aValueApplied) ...[
            const SizedBox(height: 12),
            _buildAValueBadge(),
          ],
        ],
      ),
    );
  }

  Widget _buildAValueBadge() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.safeGreen.withValues(alpha:0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.safeGreen.withValues(alpha:0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.verified_rounded,
              color: AppColors.safeGreen, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "A값 ${_formatPriceKorean(_aValue.toDouble())} 자동 적용됨",
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.safeGreen,
              ),
            ),
          ),
          const GlossaryChip(term: 'A값'),
        ],
      ),
    );
  }

  Widget _buildPriceRow(String label, String value,
      {bool isBold = false, bool highlight = false, String? glossaryTerm}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 13,
                color: highlight ? AppColors.dangerRed : AppColors.textSub,
              ),
            ),
            if (glossaryTerm != null) GlossaryChip(term: glossaryTerm),
          ],
        ),
        Text(
          value,
          style: TextStyle(
            fontSize: isBold ? 16 : 14,
            fontWeight: isBold ? FontWeight.w700 : FontWeight.w500,
            color: highlight ? AppColors.dangerRed : AppColors.textMain,
          ),
        ),
      ],
    );
  }

  /// 슬라이더 섹션
  Widget _buildSliderSection() {
    final activeColor = _isDanger
        ? AppColors.dangerRed
        : (_isWarning ? AppColors.warningOrange : AppColors.safeGreen);

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _isDanger
            ? AppColors.dangerRed.withValues(alpha:0.1)
            : AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: _isDanger ? AppColors.dangerRed : AppColors.divider,
          width: _isDanger ? 2 : 1,
        ),
      ),
      child: Column(
        children: [
          const Text("사정률",
              style: TextStyle(fontSize: 13, color: AppColors.textSub)),
          const SizedBox(height: 8),
          Text(
            "${_rate > 0 ? '+' : ''}${_rate.toStringAsFixed(4)}%",
            style: TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.w800,
              color: activeColor,
            ),
          ),
          const SizedBox(height: 20),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: 10,
              activeTrackColor: activeColor,
              inactiveTrackColor: AppColors.backgroundGrey,
              thumbColor: Colors.white,
              thumbShape: const RoundSliderThumbShape(
                enabledThumbRadius: 14,
                elevation: 4,
              ),
              overlayColor: activeColor.withValues(alpha:0.2),
            ),
            child: Slider(
              value: _rate < _minSafeRate ? _minSafeRate : _rate,
              min: _minSafeRate > -15.0 ? _minSafeRate : -15.0,
              max: 5.0,
              onChanged: (value) {
                _updateRate(double.parse(value.toStringAsFixed(2)));
              },
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildFineTuneButton(-0.01, activeColor),
              const SizedBox(width: 12),
              _buildFineTuneButton(-0.1, activeColor),
              const SizedBox(width: 24),
              _buildFineTuneButton(0.1, activeColor),
              const SizedBox(width: 12),
              _buildFineTuneButton(0.01, activeColor),
            ],
          ),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                    "${(_minSafeRate > -15.0 ? _minSafeRate : -15.0).toStringAsFixed(1)}%",
                    style:
                        const TextStyle(fontSize: 11, color: AppColors.textSub)),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.dangerRed.withValues(alpha:0.1),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    "하한선: ${_minRate.toStringAsFixed(3)}%",
                    style: const TextStyle(
                        fontSize: 10, color: AppColors.dangerRed),
                  ),
                ),
                const Text("+5%",
                    style: TextStyle(fontSize: 11, color: AppColors.textSub)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFineTuneButton(double amount, Color color) {
    final label = amount > 0 ? "+$amount %" : "$amount %";
    return InkWell(
      onTap: () => _updateRate(_rate + amount),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          border: Border.all(color: color.withValues(alpha:0.3)),
          borderRadius: BorderRadius.circular(8),
          color: color.withValues(alpha:0.05),
        ),
        child: Text(label,
            style:
                TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
      ),
    );
  }

  /// 결과 카드
  Widget _buildResultCard() {
    final statusColor = _isDanger
        ? AppColors.dangerRed
        : (_isWarning ? AppColors.warningOrange : AppColors.safeGreen);

    String statusText;
    if (_isBelowNetCost) {
      statusText = "투찰 불가 (순공사원가 미달)";
    } else if (_isDanger) {
      statusText = "투찰 불가 (하한선 미달)";
    } else if (_isWarning) {
      statusText = "주의 (하한선 근접)";
    } else {
      statusText = "안전한 투찰 구간";
    }

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _isDanger ? AppColors.dangerRed : AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: _isDanger ? AppColors.dangerRed : AppColors.divider,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha:0.05),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        children: [
          Text("투찰금액",
              style: TextStyle(
                  fontSize: 13,
                  color: _isDanger ? Colors.white70 : AppColors.textSub)),
          const SizedBox(height: 8),
          Text(
            _formatPriceKorean(_bidPrice.toDouble()),
            style: TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.w800,
              color: _isDanger ? Colors.white : AppColors.textMain,
            ),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: _isDanger
                  ? Colors.white.withValues(alpha:0.2)
                  : statusColor.withValues(alpha:0.1),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  _isDanger
                      ? Icons.warning_rounded
                      : (_isWarning
                          ? Icons.error_outline_rounded
                          : Icons.check_circle_rounded),
                  size: 16,
                  color: _isDanger ? Colors.white : statusColor,
                ),
                const SizedBox(width: 6),
                Text(
                  statusText,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: _isDanger ? Colors.white : statusColor,
                  ),
                ),
              ],
            ),
          ),
          if (!_isDanger) ...[
            const SizedBox(height: 12),
            Text(
              "하한선 대비 여유: +${_distanceFromLimit.toStringAsFixed(1)}%",
              style: const TextStyle(fontSize: 12, color: AppColors.textSub),
            ),
          ],
        ],
      ),
    );
  }

  /// 액션 버튼
  Widget _buildActionButtons() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ElevatedButton.icon(
          onPressed: (_isDanger || _isCopying) ? null : _copyBidPrice,
          icon: _isCopying
              ? const SizedBox(
                  width: 18, height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.copy_rounded, size: 20),
          label: Text(_isDanger
              ? "하한선 미달 - 복사 불가"
              : _isCopying
                  ? "처리 중..."
                  : _hasFreeToday
                      ? "투찰금액 복사하기 (무료 1회)"
                      : "투찰금액 복사하기 (500P)"),
          style: ElevatedButton.styleFrom(
            backgroundColor:
                _isDanger ? Colors.grey[400] : AppColors.primaryBlue,
            foregroundColor: Colors.white,
            disabledBackgroundColor: Colors.grey[300],
            disabledForegroundColor: Colors.grey[500],
            padding: const EdgeInsets.symmetric(vertical: 16),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            elevation: 0,
          ),
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppColors.primaryBlue.withValues(alpha:0.05),
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Row(
            children: [
              Icon(Icons.school_outlined, size: 18, color: AppColors.primaryBlue),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  "사정률이란 기초금액 대비 투찰 금액의 비율입니다.\n예: -5% = 기초금액의 95%로 투찰",
                  style: TextStyle(
                    fontSize: 12,
                    color: AppColors.textSub,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  void _updateRate(double newRate) {
    final minRate = _minSafeRate > -15.0 ? _minSafeRate : -15.0;
    final clampedRate = newRate.clamp(minRate, 5.0);
    setState(() => _rate = clampedRate);
    if (_isDanger) {
      HapticFeedback.heavyImpact();
    } else {
      HapticFeedback.lightImpact();
    }
  }

  bool _isCopying = false;

  Future<void> _copyBidPrice() async {
    if (_isCopying) return;
    setState(() => _isCopying = true);

    try {
      final result = await _apiService.deductPoints(widget.notice.bidNo);
      Clipboard.setData(ClipboardData(text: _bidPrice.toString()));
      HapticFeedback.mediumImpact();
      final wasFree = result['was_free'] == true;
      AnalyticsService().logBidCopied(bidNo: widget.notice.bidNo, wasFree: wasFree);
      if (mounted) {
        if (wasFree) {
          setState(() => _hasFreeToday = false);
          SnackBarUtils.showSuccess(context, '무료 복사 완료! ${_formatPriceKorean(_bidPrice.toDouble())}');
        } else {
          SnackBarUtils.showCopied(context, _formatPriceKorean(_bidPrice.toDouble()));
        }
      }
    } catch (e) {
      HapticFeedback.heavyImpact();
      if (mounted) {
        final msg = e.toString().replaceFirst('Exception: ', '');
        if (msg.contains('포인트') || msg.contains('402')) {
          SnackBarUtils.showError(context, '포인트가 부족합니다. 충전 후 이용해주세요');
        } else {
          // 네트워크 에러 등의 경우 무료 복사 허용
          Clipboard.setData(ClipboardData(text: _bidPrice.toString()));
          SnackBarUtils.showCopied(context, _formatPriceKorean(_bidPrice.toDouble()));
        }
      }
    } finally {
      if (mounted) setState(() => _isCopying = false);
    }
  }

  String _formatPriceKorean(double price) => formatPriceKorean(price);
}
