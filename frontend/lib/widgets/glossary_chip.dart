import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../utils/glossary.dart';

/// 용어 옆에 ⓘ 아이콘을 표시하고, 탭하면 BottomSheet로 설명을 보여주는 위젯.
///
/// 사용 예:
/// ```dart
/// Row(children: [
///   Text('기초금액'),
///   GlossaryChip(term: '기초금액'),
/// ])
/// ```
class GlossaryChip extends StatelessWidget {
  final String term;

  const GlossaryChip({super.key, required this.term});

  @override
  Widget build(BuildContext context) {
    final entry = bidGlossary[term];
    if (entry == null) return const SizedBox.shrink();

    return GestureDetector(
      onTap: () => _showGlossary(context, entry),
      child: Padding(
        padding: const EdgeInsets.only(left: 4),
        child: Icon(
          Icons.info_outline_rounded,
          size: 16,
          color: AppColors.textSub.withValues(alpha: 0.6),
        ),
      ),
    );
  }

  static void _showGlossary(BuildContext context, GlossaryEntry entry) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
        decoration: const BoxDecoration(
          color: AppColors.surfaceWhite,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Drag handle
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            // Term badge
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.primaryBlue.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                entry.term,
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.primaryBlue,
                  fontFamily: 'Pretendard',
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Simple explanation
            Text(
              entry.simple,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
                fontFamily: 'Pretendard',
                height: 1.4,
              ),
            ),
            const SizedBox(height: 12),
            // Detail explanation
            Text(
              entry.detail,
              style: const TextStyle(
                fontSize: 14,
                color: Color(0xFF4E5968),
                fontFamily: 'Pretendard',
                height: 1.6,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
