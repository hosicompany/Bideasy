import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import '../models/notice.dart';
import '../services/api_service.dart';
import '../theme/style.dart';

class BidVerifyCard extends StatefulWidget {
  final Notice notice;

  const BidVerifyCard({super.key, required this.notice});

  @override
  State<BidVerifyCard> createState() => _BidVerifyCardState();
}

class _BidVerifyCardState extends State<BidVerifyCard> {
  final ApiService _apiService = ApiService();
  final TextEditingController _priceController = TextEditingController();
  final _numberFormat = NumberFormat('#,###');
  Map<String, dynamic>? _result;
  bool _isLoading = false;

  Future<void> _verify() async {
    final text = _priceController.text.replaceAll(RegExp(r'[^0-9]'), '');
    if (text.isEmpty) return;

    final myPrice = double.tryParse(text);
    if (myPrice == null || myPrice <= 0) return;

    setState(() => _isLoading = true);

    try {
      final result = await _apiService.verifyBid(
        bidNo: widget.notice.bidNo,
        myBidPrice: myPrice,
        basicPrice: widget.notice.basicPrice,
        organization: widget.notice.organization ?? '',
      );
      if (mounted) {
        setState(() {
          _result = result;
          _isLoading = false;
        });
        HapticFeedback.mediumImpact();
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('분석 실패: $e')),
        );
      }
    }
  }

  @override
  void dispose() {
    _priceController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
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
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
            child: Row(
              children: [
                const Icon(
                  Icons.fact_check_rounded,
                  size: 18,
                  color: AppColors.primaryBlue,
                ),
                const SizedBox(width: 8),
                const Text(
                  '내 투찰 결과 분석',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textMain,
                    fontFamily: 'Pretendard',
                  ),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primaryBlue.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Text(
                    '역검증',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: AppColors.primaryBlue,
                      fontFamily: 'Pretendard',
                    ),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1, color: AppColors.divider),

          // Input
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '내 투찰가를 입력하면 결과를 분석해드려요',
                  style: TextStyle(
                    fontSize: 13,
                    color: AppColors.textSub,
                    fontFamily: 'Pretendard',
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _priceController,
                        keyboardType: TextInputType.number,
                        inputFormatters: [
                          FilteringTextInputFormatter.digitsOnly,
                          _PriceInputFormatter(),
                        ],
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          fontFamily: 'Pretendard',
                        ),
                        decoration: InputDecoration(
                          hintText: '투찰가 입력',
                          hintStyle: TextStyle(
                            color: Colors.grey[400],
                            fontWeight: FontWeight.w400,
                          ),
                          suffixText: '원',
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 12,
                          ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide: const BorderSide(
                              color: AppColors.divider,
                            ),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide: const BorderSide(
                              color: AppColors.divider,
                            ),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide: const BorderSide(
                              color: AppColors.primaryBlue,
                              width: 1.5,
                            ),
                          ),
                        ),
                        onSubmitted: (_) => _verify(),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      height: 48,
                      child: ElevatedButton(
                        onPressed: _isLoading ? null : _verify,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.primaryBlue,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          elevation: 0,
                        ),
                        child: _isLoading
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text(
                                '분석',
                                style: TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontFamily: 'Pretendard',
                                ),
                              ),
                      ),
                    ),
                  ],
                ),

                // Result
                if (_result != null) ...[
                  const SizedBox(height: 20),
                  _buildResult(_result!),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildResult(Map<String, dynamic> data) {
    if (data['found'] != true) {
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.backgroundGrey,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          data['message'] ?? '개찰 결과를 찾을 수 없습니다.',
          style: const TextStyle(
            fontSize: 14,
            color: AppColors.textSub,
            fontFamily: 'Pretendard',
          ),
        ),
      );
    }

    final myRate = (data['my_rate'] as num?)?.toDouble() ?? 0;
    final winRate = (data['winning_rate'] as num?)?.toDouble() ?? 0;
    final winPrice = (data['winning_price'] as num?)?.toDouble() ?? 0;
    final gap = (data['gap'] as num?)?.toDouble() ?? 0;
    final myRank = data['my_rank'] as int?;
    final totalPart = data['total_participants'] as int?;
    final winnerName = data['winner_name'] as String? ?? '';
    final analysis = data['analysis'] as String? ?? '';
    final tip = data['tip'] as String? ?? '';

    final isClose = gap.abs() < 0.3;
    final accentColor = isClose ? AppColors.competitionOrange : AppColors.primaryBlue;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Rate comparison
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: accentColor.withValues(alpha: 0.05),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: accentColor.withValues(alpha: 0.15),
            ),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  Expanded(
                    child: _buildRateColumn(
                      '내 투찰률',
                      '${myRate.toStringAsFixed(2)}%',
                      AppColors.textMain,
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: gap.abs() < 0.3
                          ? AppColors.competitionOrange.withValues(alpha: 0.12)
                          : AppColors.backgroundGrey,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '${gap > 0 ? "+" : ""}${gap.toStringAsFixed(2)}%p',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: gap.abs() < 0.3
                            ? AppColors.competitionOrange
                            : AppColors.textSub,
                        fontFamily: 'Pretendard',
                      ),
                    ),
                  ),
                  Expanded(
                    child: _buildRateColumn(
                      '낙찰률',
                      '${winRate.toStringAsFixed(2)}%',
                      AppColors.primaryBlue,
                    ),
                  ),
                ],
              ),
              if (myRank != null && totalPart != null) ...[
                const SizedBox(height: 12),
                const Divider(height: 1, color: AppColors.divider),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _buildSmallStat(
                      '예상 순위',
                      '$myRank위',
                    ),
                    _buildSmallStat(
                      '참여업체',
                      '$totalPart개사',
                    ),
                    _buildSmallStat(
                      '낙찰가',
                      '${_numberFormat.format(winPrice.toInt())}원',
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),

        // Winner info
        if (winnerName.isNotEmpty && winnerName != '정보 없음') ...[
          const SizedBox(height: 8),
          Text(
            '낙찰 업체: $winnerName',
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textSub,
              fontFamily: 'Pretendard',
            ),
          ),
        ],

        // Analysis comment
        if (analysis.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.backgroundGrey,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isClose ? '😮 ' : '📊 ',
                  style: const TextStyle(fontSize: 14),
                ),
                Expanded(
                  child: Text(
                    analysis,
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

        // Tip
        if (tip.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('💡 ', style: TextStyle(fontSize: 12)),
              Expanded(
                child: Text(
                  tip,
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.textSub,
                    fontFamily: 'Pretendard',
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget _buildRateColumn(String label, String value, Color valueColor) {
    return Column(
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 12,
            color: AppColors.textSub,
            fontFamily: 'Pretendard',
          ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: valueColor,
            fontFamily: 'Pretendard',
          ),
        ),
      ],
    );
  }

  Widget _buildSmallStat(String label, String value) {
    return Column(
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
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: AppColors.textMain,
            fontFamily: 'Pretendard',
          ),
        ),
      ],
    );
  }
}

class _PriceInputFormatter extends TextInputFormatter {
  final _numberFormat = NumberFormat('#,###');

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    if (newValue.text.isEmpty) return newValue;
    final digits = newValue.text.replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.isEmpty) return const TextEditingValue();
    final number = int.parse(digits);
    final formatted = _numberFormat.format(number);
    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }
}
