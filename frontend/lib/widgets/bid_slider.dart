import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme/style.dart';

class BidSlider extends StatefulWidget {
  final double currentRate;
  final ValueChanged<double> onChanged;
  final bool isDangerous;

  const BidSlider({
    super.key,
    required this.currentRate,
    required this.onChanged,
    this.isDangerous = false,
  });

  @override
  State<BidSlider> createState() => _BidSliderState();
}

class _BidSliderState extends State<BidSlider> {
  @override
  Widget build(BuildContext context) {
    final activeColor =
        widget.isDangerous ? AppColors.dangerRed : AppColors.safeGreen;

    return Column(
      children: [
        // Rate Display
        Text(
          "${widget.currentRate > 0 ? '+' : ''}${widget.currentRate.toStringAsFixed(2)}%",
          style: AppTextStyles.h1.copyWith(
            color: activeColor,
          ),
        ),
        const SizedBox(height: 20),
        // Slider
        Container(
          margin: const EdgeInsets.symmetric(horizontal: 20),
          height: 48,
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: 8,
              activeTrackColor: activeColor,
              inactiveTrackColor: AppColors.backgroundGrey,
              thumbColor: AppColors.surfaceWhite,
              thumbShape: const RoundSliderThumbShape(
                  enabledThumbRadius: 12, elevation: 4),
              overlayColor: activeColor.withValues(alpha: 0.1),
            ),
            child: Slider(
              value: widget.currentRate,
              min: -15.0,
              max: 15.0,
              divisions: 400, // 0.01 step
              onChanged: (value) {
                // Haptic Feedback - lightImpact for slider interaction
                if ((value * 100).round() !=
                    (widget.currentRate * 100).round()) {
                  HapticFeedback.lightImpact();
                }
                widget.onChanged(value);
              },
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          widget.isDangerous ? "너무 낮은 가격이에요! (위험)" : "안전한 투찰 구간입니다",
          style: AppTextStyles.caption.copyWith(
            color: activeColor,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}
