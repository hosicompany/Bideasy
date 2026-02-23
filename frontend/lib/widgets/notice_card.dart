import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../models/notice.dart';
import '../models/smart_bid.dart';
import 'competition_badge.dart';

import 'package:flutter/services.dart';
import '../utils/snackbar_utils.dart';
import 'agency_profile_sheet.dart';

class NoticeCard extends StatelessWidget {
  final Notice notice;
  final VoidCallback onTap;
  final bool isFavorite;
  final VoidCallback? onFavoriteChanged;
  final CompetitionLevel? competitionLevel;

  const NoticeCard({
    super.key,
    required this.notice,
    required this.onTap,
    this.isFavorite = false,
    this.onFavoriteChanged,
    this.competitionLevel,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.05),
                blurRadius: 10,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header Row: Status Badge + Competition Badge + Star Icon
              Row(
                children: [
                  // Status Badge
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: notice.isClosed
                          ? AppColors.closedBadgeGrey
                          : AppColors.safeGreen.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      notice.isClosed ? "개찰 완료" : "안전한 공고",
                      style: TextStyle(
                        color: notice.isClosed
                            ? AppColors.closedTextGrey
                            : AppColors.safeGreen,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  // Competition Badge
                  if (competitionLevel != null) ...[
                    const SizedBox(width: 8),
                    CompetitionBadge(level: competitionLevel!),
                  ],
                  const Spacer(),
                  // Favorite Icon
                  GestureDetector(
                    onTap: onFavoriteChanged,
                    child: Icon(
                      isFavorite
                          ? Icons.star_rounded
                          : Icons.star_border_rounded,
                      color: isFavorite
                          ? AppColors.starGold
                          : AppColors.starInactive,
                      size: 28,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),

              // Bid No (New)
              GestureDetector(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: notice.bidNo));
                  HapticFeedback.lightImpact();
                  SnackBarUtils.showInfo(context, "공고번호가 복사되었어요");
                },
                child: Row(
                  children: [
                    Text(
                      "No. ${notice.bidNo}",
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.textSub,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      Icons.copy_rounded,
                      size: 12,
                      color: AppColors.textSub.withValues(alpha:0.6),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              Text(
                notice.title,
                style: AppTextStyles.h2,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),
              Text(
                "기초금액: ${notice.formattedPrice}원",
                style: AppTextStyles.body1,
              ),
              if (notice.organization != null &&
                  notice.organization!.isNotEmpty) ...[
                const SizedBox(height: 4),
                GestureDetector(
                  onTap: () {
                    AgencyProfileSheet.show(context, notice.organization!);
                  },
                  child: Text(
                    notice.organization!,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.textSub,
                      decoration: TextDecoration.underline,
                      decorationColor: AppColors.textSub,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Text(
                    "분석 보기 >",
                    style: AppTextStyles.caption.copyWith(
                      color: AppColors.primaryBlue,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              )
            ],
          ),
        ),
      ),
    );
  }
}
