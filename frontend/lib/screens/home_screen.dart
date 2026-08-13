import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'my_page_screen.dart';
import 'notification_screen.dart';
import 'bid_calculator_screen.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
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
                        ref
                            .read(noticesProvider.notifier)
                            .toggleExcludeClosed();
                      },
                      child: Row(
                        children: [
                          Checkbox(
                            value: s.excludeClosed,
                            onChanged: (_) {
                              ref
                                  .read(noticesProvider.notifier)
                                  .toggleExcludeClosed();
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
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => BidCalculatorScreen(notice: notice),
      ),
    );
  }
}
