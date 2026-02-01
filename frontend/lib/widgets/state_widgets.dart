import 'package:flutter/material.dart';
import '../theme/style.dart';

/// 로딩 상태 위젯 - 스켈레톤 UI 포함
class LoadingStateWidget extends StatelessWidget {
  final String? message;
  final int skeletonCount;

  const LoadingStateWidget({
    super.key,
    this.message,
    this.skeletonCount = 3,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
          const SizedBox(height: 40),
          const SizedBox(
            width: 40,
            height: 40,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              valueColor: AlwaysStoppedAnimation<Color>(AppColors.primaryBlue),
            ),
          ),
          if (message != null) ...[
            const SizedBox(height: 16),
            Text(
              message!,
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.textSub,
              ),
            ),
          ],
          const SizedBox(height: 32),
          // 스켈레톤 카드들
          ...List.generate(
            skeletonCount,
            (index) => const Padding(
              padding: EdgeInsets.only(bottom: 16),
              child: SkeletonNoticeCard(),
            ),
          ),
        ],
      ),
    );
  }
}

/// 스켈레톤 공고 카드
class SkeletonNoticeCard extends StatefulWidget {
  const SkeletonNoticeCard({super.key});

  @override
  State<SkeletonNoticeCard> createState() => _SkeletonNoticeCardState();
}

class _SkeletonNoticeCardState extends State<SkeletonNoticeCard>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 1500),
      vsync: this,
    )..repeat();
    _animation = Tween<double>(begin: 0.3, end: 0.6).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.03),
                blurRadius: 10,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 상단 배지
              _buildSkeletonBox(width: 70, height: 24, opacity: _animation.value),
              const SizedBox(height: 12),
              // 제목
              _buildSkeletonBox(height: 20, opacity: _animation.value),
              const SizedBox(height: 8),
              _buildSkeletonBox(width: 200, height: 20, opacity: _animation.value),
              const SizedBox(height: 12),
              // 가격
              _buildSkeletonBox(width: 150, height: 16, opacity: _animation.value),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSkeletonBox({
    double? width,
    required double height,
    required double opacity,
  }) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: Colors.grey.withOpacity(opacity),
        borderRadius: BorderRadius.circular(4),
      ),
    );
  }
}

/// 에러 상태 위젯
class ErrorStateWidget extends StatelessWidget {
  final String? title;
  final String? message;
  final VoidCallback? onRetry;
  final IconData icon;

  const ErrorStateWidget({
    super.key,
    this.title,
    this.message,
    this.onRetry,
    this.icon = Icons.error_outline_rounded,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: AppColors.dangerRed.withOpacity(0.1),
                borderRadius: BorderRadius.circular(36),
              ),
              child: Icon(
                icon,
                color: AppColors.dangerRed,
                size: 36,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              title ?? "문제가 발생했어요",
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              message ?? "잠시 후 다시 시도해주세요",
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.textSub,
                height: 1.5,
              ),
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 24),
              ElevatedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text("다시 시도"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryBlue,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 14,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  elevation: 0,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 빈 상태 위젯
class EmptyStateWidget extends StatelessWidget {
  final String? title;
  final String? message;
  final IconData icon;
  final Widget? action;

  const EmptyStateWidget({
    super.key,
    this.title,
    this.message,
    this.icon = Icons.inbox_rounded,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: AppColors.backgroundGrey,
                borderRadius: BorderRadius.circular(40),
              ),
              child: Icon(
                icon,
                color: AppColors.textSub.withOpacity(0.5),
                size: 40,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              title ?? "아직 데이터가 없어요",
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              message ?? "",
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.textSub,
                height: 1.5,
              ),
              textAlign: TextAlign.center,
            ),
            if (action != null) ...[
              const SizedBox(height: 24),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

/// 네트워크 에러 전용 위젯
class NetworkErrorWidget extends StatelessWidget {
  final VoidCallback? onRetry;

  const NetworkErrorWidget({
    super.key,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return ErrorStateWidget(
      icon: Icons.wifi_off_rounded,
      title: "네트워크 연결 오류",
      message: "인터넷 연결을 확인하고\n다시 시도해주세요",
      onRetry: onRetry,
    );
  }
}

/// 서버 에러 전용 위젯
class ServerErrorWidget extends StatelessWidget {
  final VoidCallback? onRetry;

  const ServerErrorWidget({
    super.key,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return ErrorStateWidget(
      icon: Icons.cloud_off_rounded,
      title: "서버에 연결할 수 없어요",
      message: "서버가 응답하지 않습니다.\n잠시 후 다시 시도해주세요",
      onRetry: onRetry,
    );
  }
}
