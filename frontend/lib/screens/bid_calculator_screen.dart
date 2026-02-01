import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme/style.dart';
import '../models/notice.dart';
import '../widgets/ai_analysis_card.dart';
import '../widgets/scientific_analysis_dashboard.dart';
import '../utils/snackbar_utils.dart';

/// 투찰가 계산기 (고도화 버전)
/// - 슬라이더로 사정률 조정
/// - 낙찰하한선 시각화
/// - Red Alert 모드
class BidCalculatorScreen extends StatefulWidget {
  final Notice notice;

  const BidCalculatorScreen({super.key, required this.notice});

  @override
  State<BidCalculatorScreen> createState() => _BidCalculatorScreenState();
}

class _BidCalculatorScreenState extends State<BidCalculatorScreen> {
  final double _rate = -5.0; // 사정률 (기본값 -5%)

  // A값 (고정비용) - TODO: 백엔드에서 자동 추출
  int _aValue = 0;
  bool _aValueApplied = false;

  // 순공사원가 (투찰 하한선 방어용)
  int _netCost = 0;
  bool _netCostApplied = false;

  @override
  void initState() {
    super.initState();
    // 전달받은 Notice에 A값이 있으면 자동 적용
    if (widget.notice.aValue != null && widget.notice.aValue! > 0) {
      _aValue = widget.notice.aValue!;
      _aValueApplied = true;
    }
    // 순공사원가 초기화
    if (widget.notice.netCost != null && widget.notice.netCost! > 0) {
      _netCost = widget.notice.netCost!;
      _netCostApplied = true;
    }
  }

  // 법정 낙찰하한율 (공사: 87.745%)
  static const double _lowerLimitRate = 87.745;

  // 최소 사정률 (하한선 기준)
  double get _minRate => _lowerLimitRate - 100; // -12.255%

  // 순공사원가 방어용 최소 사정률
  double get _minSafeRate {
    if (!_netCostApplied || _netCost <= 0) return -15.0;

    // 공식 역산:
    // NetCost = ((Basic - A) * (1 + rate/100)) + A
    // (NetCost - A) = (Basic - A) * (1 + rate/100)
    // (NetCost - A) / (Basic - A) = 1 + rate/100
    // rate/100 = ((NetCost - A) / (Basic - A)) - 1

    double variablePart = _basicPrice;
    double target = _netCost.toDouble();

    if (_aValueApplied) {
      variablePart = _basicPrice - _aValue;
      target = target - _aValue;
    }

    if (variablePart <= 0) return -15.0; // Should not happen

    final safeRate = ((target / variablePart) - 1) * 100;

    // 안전 마진 0.1% 추가
    return safeRate + 0.1;
  }

  // 계산된 값들
  double get _basicPrice => widget.notice.basicPrice;

  // 예정가격 범위 (±3%)
  double get _estimatedMin => _basicPrice * 0.97;
  double get _estimatedMax => _basicPrice * 1.03;

  // 투찰금액 (1원 절사) - A값 반영 공식
  int get _bidPrice {
    double target;
    if (_aValueApplied) {
      // use bool flag
      // A값 적용 공식: ((기초금액 - A값) × 사정률) + A값
      final variablePart = _basicPrice - _aValue;
      target = (variablePart * (1 + _rate / 100)) + _aValue;
    } else {
      target = _basicPrice * (1 + _rate / 100);
    }
    return (target ~/ 10) * 10;
  }

  // 낙찰하한선
  int get _lowerLimitPrice {
    final target = _basicPrice * (_lowerLimitRate / 100);
    return (target ~/ 10) * 10;
  }

  // 하한선 대비 여유율
  double get _distanceFromLimit {
    if (_lowerLimitPrice == 0) return 100.0;
    return ((_bidPrice - _lowerLimitPrice) / _lowerLimitPrice) * 100;
  }

  // 순공사원가 미달 여부
  bool get _isBelowNetCost => _netCostApplied && _bidPrice < _netCost;

  // 안전도 레벨
  String get _safetyLevel {
    if (_isBelowNetCost) return "DANGER"; // 순공사원가 방어 우선
    if (_bidPrice < _lowerLimitPrice) return "DANGER";
    if (_bidPrice < _lowerLimitPrice * 1.02) return "WARNING";
    return "SAFE";
  }

  bool get _isDanger => _safetyLevel == "DANGER";
  bool get _isWarning => _safetyLevel == "WARNING";

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _isDanger
          ? const Color(0xFFFFEBEE) // 연한 빨강
          : AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text("투찰가 계산"),
        backgroundColor:
            _isDanger ? AppColors.dangerRed : AppColors.surfaceWhite,
        foregroundColor: _isDanger ? Colors.white : AppColors.textMain,
        elevation: 0,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // 공고 정보 카드
              _buildNoticeInfoCard(),
              const SizedBox(height: 20),

              // 가격 정보 카드
              _buildPriceInfoCard(),
              const SizedBox(height: 20),

              // 슬라이더 섹션
              _buildSliderSection(),
              const SizedBox(height: 20),

              // 결과 카드
              _buildResultCard(),
              const SizedBox(height: 24),

              // Phase 3: Scientific Bidding Dashboard
              const Text(
                "🧪 과학적 분석 (Scientific Bidding)",
                style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: Colors.indigo),
              ),
              const SizedBox(height: 10),
              ScientificAnalysisDashboard(bidNo: widget.notice.bidNo),

              const SizedBox(height: 40),

              // 액션 버튼
              _buildActionButtons(),
            ],
          ),
        ),
      ),
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
          Text(
            widget.notice.organization ?? "발주처 미상",
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSub,
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
          _buildPriceRow("기초금액", _formatPrice(_basicPrice), isBold: true),
          const Divider(height: 20),
          _buildPriceRow("예정가격 범위",
              "${_formatPrice(_estimatedMin)} ~ ${_formatPrice(_estimatedMax)}"),
          const SizedBox(height: 8),
          _buildPriceRow("낙찰하한선 ($_lowerLimitRate%)",
              _formatPrice(_lowerLimitPrice.toDouble()),
              highlight: true),
          // 순공사원가 (적용된 경우에만 표시)
          if (_netCostApplied) ...[
            const SizedBox(height: 8),
            _buildPriceRow(
              "순공사원가 (투찰불가)",
              _formatPrice(_netCost.toDouble()),
              highlight: true,
            ),
          ],
          // A값 배지 (적용된 경우에만 표시)
          if (_aValueApplied) ...[
            const SizedBox(height: 12),
            _buildAValueBadge(),
          ],
        ],
      ),
    );
  }

  /// A값 자동 적용 배지
  Widget _buildAValueBadge() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.safeGreen.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.safeGreen.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.verified_rounded,
              color: AppColors.safeGreen, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "A값 ${_formatPrice(_aValue.toDouble())} 자동 적용됨",
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.safeGreen,
              ),
            ),
          ),
          const Text("✅", style: TextStyle(fontSize: 14)),
        ],
      ),
    );
  }

  Widget _buildPriceRow(String label, String value,
      {bool isBold = false, bool highlight = false}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 13,
            color: highlight ? AppColors.dangerRed : AppColors.textSub,
          ),
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
        : (_isWarning ? const Color(0xFFFF9500) : AppColors.safeGreen);

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _isDanger
            ? AppColors.dangerRed.withOpacity(0.1)
            : AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: _isDanger ? AppColors.dangerRed : AppColors.divider,
          width: _isDanger ? 2 : 1,
        ),
      ),
      child: Column(
        children: [
          // 사정률 표시
          const Text(
            "사정률",
            style: TextStyle(
              fontSize: 13,
              color: AppColors.textSub,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            "${_rate > 0 ? '+' : ''}${_rate.toStringAsFixed(4)}%", // 소수점 4자리까지 표시
            style: TextStyle(
              fontSize: 32, // 약간 축소
              fontWeight: FontWeight.w800,
              color: activeColor,
            ),
          ),
          const SizedBox(height: 20),

          // 슬라이더
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
              overlayColor: activeColor.withOpacity(0.2),
            ),
            child: Slider(
              value: _rate < _minSafeRate ? _minSafeRate : _rate,
              min: _minSafeRate > -15.0 ? _minSafeRate : -15.0,
              max: 5.0,
              divisions: null, // 연속적인 값 (미세조정 기능 보완)
              onChanged: (value) {
                // 슬라이더로는 0.01 단위로 스냅
                _updateRate(double.parse(value.toStringAsFixed(2)));
              },
            ),
          ),

          // 슬라이더 및 미세조정 섹션
          Column(
            children: [
              // 미세 조정 버튼 (New)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _buildFineTuneButton(-0.01, activeColor),
                  const SizedBox(width: 12),
                  _buildFineTuneButton(-0.1, activeColor),
                  const SizedBox(width: 24), // Spacer
                  _buildFineTuneButton(0.1, activeColor),
                  const SizedBox(width: 12),
                  _buildFineTuneButton(0.01, activeColor),
                ],
              ),
              const SizedBox(height: 12),

              // 하한선 라벨
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                        "${(_minSafeRate > -15.0 ? _minSafeRate : -15.0)
                                .toStringAsFixed(1)}%",
                        style:
                            const TextStyle(fontSize: 11, color: AppColors.textSub)),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.dangerRed.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        "하한선: ${_minRate.toStringAsFixed(3)}%",
                        style: const TextStyle(
                            fontSize: 10, color: AppColors.dangerRed),
                      ),
                    ),
                    const Text("+5%",
                        style:
                            TextStyle(fontSize: 11, color: AppColors.textSub)),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildFineTuneButton(double amount, Color color) {
    final isPositive = amount > 0;
    final label = isPositive ? "+$amount %" : "$amount %";

    return InkWell(
      onTap: () {
        _updateRate(_rate + amount);
      },
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          border: Border.all(color: color.withOpacity(0.3)),
          borderRadius: BorderRadius.circular(8),
          color: color.withOpacity(0.05),
        ),
        child: Text(
          label,
          style: TextStyle(
              fontSize: 13, fontWeight: FontWeight.w600, color: color),
        ),
      ),
    );
  }

  /// 결과 카드
  Widget _buildResultCard() {
    final statusColor = _isDanger
        ? AppColors.dangerRed
        : (_isWarning ? const Color(0xFFFF9500) : AppColors.safeGreen);

    String statusText;
    if (_isBelowNetCost) {
      statusText = "🚨 투찰 불가 (순공사원가 미달)";
    } else if (_isDanger) {
      statusText = "🚨 투찰 불가 (하한선 미달)";
    } else if (_isWarning) {
      statusText = "⚠️ 주의 (하한선 근접)";
    } else {
      statusText = "✅ 안전한 투찰 구간";
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
            color: Colors.black.withOpacity(0.05),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        children: [
          Text(
            "투찰금액",
            style: TextStyle(
              fontSize: 13,
              color: _isDanger ? Colors.white70 : AppColors.textSub,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _formatPrice(_bidPrice.toDouble()),
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
                  ? Colors.white.withOpacity(0.2)
                  : statusColor.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              statusText,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: _isDanger ? Colors.white : statusColor,
              ),
            ),
          ),
          if (!_isDanger) ...[
            const SizedBox(height: 12),
            Text(
              "하한선 대비 여유: +${_distanceFromLimit.toStringAsFixed(1)}%",
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSub,
              ),
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
        // 복사 버튼
        ElevatedButton.icon(
          onPressed: _isDanger ? null : _copyBidPrice,
          icon: const Icon(Icons.copy_rounded, size: 20),
          label: Text(_isDanger ? "하한선 미달 - 복사 불가" : "투찰금액 복사하기"),
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
        // 초보자 안내
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppColors.primaryBlue.withOpacity(0.05),
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Row(
            children: [
              Icon(Icons.school_outlined,
                  size: 18, color: AppColors.primaryBlue),
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

  void _copyBidPrice() {
    Clipboard.setData(ClipboardData(text: _bidPrice.toString()));
    HapticFeedback.mediumImpact();
    SnackBarUtils.showCopied(context, _formatPrice(_bidPrice.toDouble()));
  }

  String _formatPrice(double price) {
    if (price >= 100000000) {
      return "${(price / 100000000).toStringAsFixed(1)}억원";
    } else if (price >= 10000) {
      return "${(price / 10000).toStringAsFixed(0)}만원";
    }
    return "${price.toStringAsFixed(0)}원";
  }
}
