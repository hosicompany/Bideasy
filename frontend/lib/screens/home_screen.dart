import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'my_page_screen.dart';
import 'notification_screen.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
import '../widgets/bid_slider.dart';
import '../widgets/ai_analysis_card.dart';
import '../widgets/opening_result_table.dart';
import '../widgets/state_widgets.dart';
import '../utils/snackbar_utils.dart';
import '../models/notice.dart';
import '../providers/notices_provider.dart';
import '../providers/notification_provider.dart';
import '../services/analytics_service.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final ScrollController _scrollController = ScrollController();
  late TextEditingController _searchController;
  final FocusNode _searchFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController();
    _scrollController.addListener(_scrollListener);

    // Initialize provider (loads filters + fetches data)
    Future(() {
      ref.read(noticesProvider.notifier).init().then((_) {
        // Sync search controller with loaded keyword
        final keyword = ref.read(noticesProvider).keyword;
        _searchController.text = keyword ?? '';
      });
      // Fetch unread notification count for badge
      ref.read(notificationProvider.notifier).fetchUnreadCount();
    });
  }

  void _scrollListener() {
    if (_scrollController.position.pixels ==
        _scrollController.position.maxScrollExtent) {
      final s = ref.read(noticesProvider);
      if (!s.isLoading && !s.isLoadingMore) {
        ref.read(noticesProvider.notifier).loadMore();
      }
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocusNode.dispose();
    super.dispose();
  }

  void _triggerSearch() {
    _searchFocusNode.unfocus();
    final keyword = _searchController.text;
    ref.read(noticesProvider.notifier).search(keyword);
    if (keyword.isNotEmpty) {
      AnalyticsService().logSearch(keyword);
    }
  }

  Future<void> _toggleFavorite(String bidNo) async {
    HapticFeedback.lightImpact();
    try {
      await ref.read(noticesProvider.notifier).toggleFavorite(bidNo);
    } catch (_) {
      if (mounted) {
        SnackBarUtils.showError(context, "즐겨찾기 변경에 실패했어요");
      }
    }
  }

  Future<void> _refreshNotices() async {
    try {
      await ref.read(noticesProvider.notifier).refreshNotices();
      if (mounted) {
        final keyword = ref.read(noticesProvider).keyword;
        SnackBarUtils.showSuccess(
          context,
          keyword != null ? "검색 결과가 업데이트됐어요" : "최신 공고를 불러왔어요",
        );
      }
    } catch (_) {
      if (mounted) {
        SnackBarUtils.showError(context, "업데이트에 실패했어요. 다시 시도해주세요");
      }
    }
  }

  Widget _buildNotificationBell() {
    final unreadCount = ref.watch(notificationProvider).unreadCount;
    return IconButton(
      icon: Badge(
        isLabelVisible: unreadCount > 0,
        label: Text(
          unreadCount > 99 ? '99+' : '$unreadCount',
          style: const TextStyle(fontSize: 10, color: Colors.white),
        ),
        child: const Icon(Icons.notifications_outlined),
      ),
      tooltip: '알림',
      onPressed: () {
        HapticFeedback.lightImpact();
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const NotificationScreen()),
        ).then((_) {
          // Refresh count when returning from notification screen
          ref.read(notificationProvider.notifier).fetchUnreadCount();
        });
      },
    );
  }

  Widget _buildNoticeList({bool isFavoriteTab = false}) {
    final s = ref.watch(noticesProvider);

    // 1. Favorites Tab
    if (isFavoriteTab) {
      if (s.favorites.isEmpty && s.favoriteIds.isEmpty) {
        return const EmptyStateWidget(
          icon: Icons.star_border_rounded,
          title: "즐겨찾기한 공고가 없어요",
          message: "관심 있는 공고의 별 아이콘을 눌러\n즐겨찾기에 추가해보세요",
        );
      }
      return RefreshIndicator(
        onRefresh: _refreshNotices,
        color: AppColors.primaryBlue,
        child: ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          itemCount: s.favorites.length,
          itemBuilder: (context, index) {
            final notice = s.favorites[index];
            return NoticeCard(
              key: ValueKey(notice.bidNo),
              notice: notice,
              isFavorite: true,
              competitionLevel: s.competitionCache[notice.bidNo],
              onFavoriteChanged: () => _toggleFavorite(notice.bidNo),
              onTap: () => _showCalculator(context, notice),
            );
          },
        ),
      );
    }

    // 2. Main Feed (Infinite Scroll)
    if (s.isLoading && s.notices.isEmpty) {
      return const LoadingStateWidget(
          message: "최신 공고를 불러옵니다...", skeletonCount: 4);
    }

    if (s.notices.isEmpty) {
      return EmptyStateWidget(
        icon: Icons.search_off_rounded,
        title: s.keyword != null ? "검색 결과가 없어요" : "공고가 없어요",
        message: s.keyword != null
            ? "'${s.keyword}' 검색 결과가 없습니다."
            : "새로운 공고가 등록되면 알려드릴게요",
        action: s.keyword != null
            ? TextButton.icon(
                onPressed: () {
                  _searchController.clear();
                  _triggerSearch();
                },
                icon: const Icon(Icons.clear, size: 18),
                label: const Text("검색어 지우기"),
              )
            : null,
      );
    }

    return RefreshIndicator(
      onRefresh: _refreshNotices,
      color: AppColors.primaryBlue,
      child: ListView.builder(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: s.notices.length + (s.isLoadingMore ? 1 : 0),
        itemBuilder: (context, index) {
          if (index == s.notices.length) {
            return const Padding(
              padding: EdgeInsets.all(20.0),
              child: Center(child: CircularProgressIndicator()),
            );
          }

          final notice = s.notices[index];
          final isFav = s.favoriteIds.contains(notice.bidNo);
          return NoticeCard(
            key: ValueKey(notice.bidNo),
            notice: notice,
            isFavorite: isFav,
            competitionLevel: s.competitionCache[notice.bidNo],
            onFavoriteChanged: () => _toggleFavorite(notice.bidNo),
            onTap: () => _showCalculator(context, notice),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(noticesProvider);

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          toolbarHeight: 70,
          title: Container(
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.backgroundGrey,
              borderRadius: BorderRadius.circular(12),
            ),
            child: TextField(
              controller: _searchController,
              focusNode: _searchFocusNode,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: "공고명, 키워드 검색",
                hintStyle: TextStyle(color: Colors.grey[500], fontSize: 14),
                prefixIcon: IconButton(
                  icon: const Icon(Icons.search, color: Colors.grey),
                  onPressed: _triggerSearch,
                ),
                suffixIcon: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Exclude Closed Checkbox
                    InkWell(
                      onTap: () {
                        ref.read(noticesProvider.notifier).toggleExcludeClosed();
                      },
                      child: Row(
                        children: [
                          Checkbox(
                            value: s.excludeClosed,
                            onChanged: (_) {
                              ref.read(noticesProvider.notifier).toggleExcludeClosed();
                            },
                            materialTapTargetSize:
                                MaterialTapTargetSize.shrinkWrap,
                            visualDensity: VisualDensity.compact,
                          ),
                          Text("종료숨김",
                              style: TextStyle(
                                  fontSize: 12, color: Colors.grey[700])),
                          const SizedBox(width: 8),
                        ],
                      ),
                    ),
                    // Clear Button
                    ValueListenableBuilder<TextEditingValue>(
                      valueListenable: _searchController,
                      builder: (context, value, child) {
                        if (value.text.isEmpty) return const SizedBox.shrink();
                        return IconButton(
                          icon: const Icon(Icons.clear, size: 20),
                          onPressed: () {
                            _searchController.clear();
                            _triggerSearch();
                          },
                        );
                      },
                    ),
                  ],
                ),
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
              onSubmitted: (_) => _triggerSearch(),
            ),
          ),
          bottom: const TabBar(
            tabs: [
              Tab(text: "전체 공고"),
              Tab(text: "즐겨찾기"),
            ],
            indicatorColor: AppColors.primaryBlue,
            labelColor: AppColors.primaryBlue,
            unselectedLabelColor: Colors.grey,
          ),
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: '새로고침',
              onPressed: _refreshNotices,
            ),
            _buildNotificationBell(),
            IconButton(
              icon: const Icon(Icons.person),
              tooltip: '마이페이지',
              onPressed: () {
                Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (context) => const MyPageScreen()));
              },
            )
          ],
        ),
        body: TabBarView(
          children: [
            // Tab 1: Feed
            _buildNoticeList(),
            // Tab 2: Favorites
            _buildNoticeList(isFavoriteTab: true),
          ],
        ),
      ),
    );
  }

  void _showCalculator(BuildContext context, Notice notice) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        minChildSize: 0.5,
        builder: (_, controller) => Container(
          decoration: const BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: CalculatorView(notice: notice),
        ),
      ),
    );
  }
}

class CalculatorView extends StatefulWidget {
  final Notice notice;
  const CalculatorView({super.key, required this.notice});

  @override
  State<CalculatorView> createState() => _CalculatorViewState();
}

class _CalculatorViewState extends State<CalculatorView> {
  double _rate = 0.0;

  // Logic from backend/app/services/calculator.py
  // Real Logic: Calculate Lower Limit Rate based on Contract Type
  double get _lowerLimitRate {
    // 법정 낙찰하한율 (국가계약법 기준, backend/app/services/calculator.py와 동기화)
    switch (widget.notice.contractType) {
      case 'SERVICE':
        return 60.0;    // 용역
      case 'GOODS':
        return 0.0;     // 물품 (최저가 방식, 하한선 없음)
      case 'CONSTRUCTION':
      default:
        return 87.745;  // 공사
    }
  }

  // Calculate the rate difference from standard (100%) that corresponds to the lower limit
  // e.g. 87.745% means -12.255% from basic price
  double get _dangerousThreshold => _lowerLimitRate - 100.0;

  int get _calculatedPrice {
    double target = widget.notice.basicPrice * (1 + _rate / 100);
    return (target / 10).floor() * 10;
  }

  // Check safety: If user rate is BELOW the threshold
  bool get _isDangerous => _rate < _dangerousThreshold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16, left: 24, right: 24, bottom: 24),
      child: Column(
        children: [
          // Handle Bar and Close Button Row
          Stack(
            alignment: Alignment.center,
            children: [
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: IconButton(
                  icon: const Icon(Icons.close, color: AppColors.textMain),
                  onPressed: () => Navigator.pop(context),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // Scrollable Content
          Expanded(
            child: ListView(
              controller: ScrollController(),
              padding: EdgeInsets.zero,
              children: [
                Text(widget.notice.title, style: AppTextStyles.h2),
                const SizedBox(height: 8),
                Text("기초금액: ${widget.notice.formattedPrice}원",
                    style: AppTextStyles.body1),
                const SizedBox(height: 32),
                if (widget.notice.isClosed) ...[
                  // Closed View: Result Table
                  OpeningResultTable(notice: widget.notice),
                  const SizedBox(height: 32),
                  const Divider(),
                  const SizedBox(height: 16),
                  AiAnalysisCard(
                      notice: widget.notice), // Optional: Keep for reference
                ] else ...[
                  // Active View: Calculator
                  Center(
                    child: Text(
                      "${_calculatedPrice.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (Match m) => '${m[1]},')}원",
                      style: AppTextStyles.h1.copyWith(fontSize: 32),
                    ),
                  ),
                  const SizedBox(height: 32),

                  AiAnalysisCard(notice: widget.notice),

                  const SizedBox(height: 24),

                  BidSlider(
                    currentRate: _rate,
                    isDangerous: _isDangerous,
                    onChanged: (val) {
                      setState(() => _rate = val);
                    },
                  ),
                  const SizedBox(height: 24),
                ],
              ],
            ),
          ),

          // Action Button (Hide if closed)
          if (!widget.notice.isClosed) ...[
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isDangerous
                    ? null
                    : () {
                        Clipboard.setData(ClipboardData(text: _calculatedPrice.toString()));
                        HapticFeedback.mediumImpact();
                        SnackBarUtils.showSuccess(context, '투찰가 $_calculatedPrice원이 복사됐어요');
                        Navigator.pop(context);
                      },
                style: ElevatedButton.styleFrom(
                  backgroundColor: _isDangerous
                      ? AppColors.dangerRed
                      : AppColors.primaryBlue,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16)),
                  disabledBackgroundColor: AppColors.backgroundGrey,
                ),
                child: const Text("이 가격으로 저장하기",
                    style:
                        TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
