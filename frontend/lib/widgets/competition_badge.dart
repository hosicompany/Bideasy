import 'package:flutter/material.dart';
import '../models/smart_bid.dart';

/// 경쟁 강도 알약형 배지
class CompetitionBadge extends StatelessWidget {
  final CompetitionLevel level;
  final bool compact;

  const CompetitionBadge({
    super.key,
    required this.level,
    this.compact = true,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 12,
        vertical: compact ? 4 : 6,
      ),
      decoration: BoxDecoration(
        color: level.color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        '${level.emoji} ${level.label}',
        style: TextStyle(
          color: level.color,
          fontSize: compact ? 11 : 13,
          fontWeight: FontWeight.w600,
          fontFamily: 'Pretendard',
        ),
      ),
    );
  }
}
