import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'my_page_screen.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
import '../widgets/bid_slider.dart';
import '../widgets/ai_analysis_card.dart';
import '../widgets/opening_result_table.dart';
import '../widgets/state_widgets.dart';
import '../utils/snackbar_utils.dart';
import '../models/notice.dart';
import '../services/api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ApiService apiService = ApiService();
  late Future<List<Notice>> futureNotices;
  late Future<List<Notice>> futureFavorites;
  String? _keyword;
  final Set<String> _favoriteIds = {};
  bool _excludeClosed = false;

  late TextEditingController _searchController;
  final FocusNode _searchFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(); // Initialize empty first
    // Initialize futureNotices immediately to prevent LateInitializationError
    futureNotices = apiService.fetchNotices();
    futureFavorites = Future.value([]);
    _loadFilters();
    _fetchFavorites();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocusNode.dispose();
    super.dispose();
  }

  Future<void> _loadFilters() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _keyword = prefs.getString('keyword');
      _searchController.text = _keyword ?? ""; // Sync controller
      _excludeClosed = prefs.getBool('exclude_closed') ?? false;

      futureNotices = apiService.fetchNotices(
          keyword: _keyword, excludeClosed: _excludeClosed);
    });
  }

  Future<void> _saveFilter({String? keyword, bool? excludeClosed}) async {
    final prefs = await SharedPreferences.getInstance();
    if (keyword != null) {
      if (keyword.isEmpty) {
        await prefs.remove('keyword');
      } else {
        await prefs.setString('keyword', keyword);
      }
    }
    if (excludeClosed != null) {
      await prefs.setBool('exclude_closed', excludeClosed);
    }
  }

  Future<void> _fetchFavorites() async {
    try {
      final favorites = await apiService.fetchFavorites();
      setState(() {
        _favoriteIds.clear();
        _favoriteIds.addAll(favorites.map((n) => n.bidNo));
        futureFavorites = Future.value(favorites);
      });
    } catch (e) {
      // Handle error cleanly or log
      print("Failed to fetch favorites: $e");
      futureFavorites = Future.value([]);
    }
  }

  Future<void> _toggleFavorite(String bidNo) async {
    try {
      // Haptic Feedback for favorite toggle
      HapticFeedback.lightImpact();
      // Optimistic Update
      setState(() {
        if (_favoriteIds.contains(bidNo)) {
          _favoriteIds.remove(bidNo);
        } else {
          _favoriteIds.add(bidNo);
        }
      });
      // Call Backend
      await apiService.toggleFavorite(bidNo);
      // Refresh Favorites List in background
      _fetchFavorites();
    } catch (e) {
      // Revert if failed
      setState(() {
        if (_favoriteIds.contains(bidNo)) {
          _favoriteIds.remove(bidNo);
        } else {
          _favoriteIds.add(bidNo);
        }
      });
      if (mounted) {
        SnackBarUtils.showError(context, "즐겨찾기 변경에 실패했어요");
      }
    }
  }

  Future<void> _refreshNotices() async {
    try {
      await apiService.triggerCrawl(); // Still crawl all
      await _fetchFavorites(); // Sync favorites
      setState(() {
        futureNotices = apiService.fetchNotices(
            keyword: _keyword, excludeClosed: _excludeClosed);
      });
      if (mounted) {
        SnackBarUtils.showSuccess(
          context,
          _keyword != null ? "검색 결과가 업데이트됐어요" : "최신 공고를 불러왔어요",
        );
      }
    } catch (e) {
      if (mounted) {
        SnackBarUtils.showError(context, "업데이트에 실패했어요. 다시 시도해주세요");
      }
    }
  }

  Widget _buildNoticeList(Future<List<Notice>> futureList,
      {bool isFavoriteTab = false}) {
    return FutureBuilder<List<Notice>>(
      future: futureList,
      builder: (context, snapshot) {
        // 로딩 상태
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const LoadingStateWidget(
            message: "공고를 불러오는 중...",
            skeletonCount: 4,
          );
        }

        // 에러 상태
        if (snapshot.hasError) {
          final errorMsg = snapshot.error.toString();
          // 네트워크/서버 에러 구분
          if (errorMsg.contains('SocketException') ||
              errorMsg.contains('Connection refused')) {
            return NetworkErrorWidget(
              onRetry: _refreshNotices,
            );
          }
          return ErrorStateWidget(
            title: "공고를 불러오지 못했어요",
            message: "잠시 후 다시 시도해주세요",
            onRetry: _refreshNotices,
          );
        }

        // 빈 상태
        if (!snapshot.hasData || snapshot.data!.isEmpty) {
          if (isFavoriteTab) {
            return EmptyStateWidget(
              icon: Icons.star_border_rounded,
              title: "즐겨찾기한 공고가 없어요",
              message: "관심 있는 공고의 별 아이콘을 눌러\n즐겨찾기에 추가해보세요",
            );
          }
          return EmptyStateWidget(
            icon: Icons.search_off_rounded,
            title: _keyword != null ? "검색 결과가 없어요" : "공고가 없어요",
            message: _keyword != null
                ? "'$_keyword' 검색 결과가 없습니다.\n다른 키워드로 검색해보세요"
                : "새로운 공고가 등록되면 알려드릴게요",
            action: _keyword != null
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

        final notices = snapshot.data!;
        return RefreshIndicator(
          onRefresh: _refreshNotices,
          color: AppColors.primaryBlue,
          child: ListView.builder(
            physics: const AlwaysScrollableScrollPhysics(),
            itemCount: notices.length,
            itemBuilder: (context, index) {
              final notice = notices[index];
              final isFav = _favoriteIds.contains(notice.bidNo);
              return NoticeCard(
                notice: notice,
                isFavorite: isFav,
                onFavoriteChanged: () => _toggleFavorite(notice.bidNo),
                onTap: () {
                  _showCalculator(context, notice);
                },
              );
            },
          ),
        );
      },
    );
  }

  void _triggerSearch() {
    // Dismiss keyboard
    _searchFocusNode.unfocus();

    final newKeyword = _searchController.text.trim();
    setState(() {
      _keyword = newKeyword.isEmpty ? null : newKeyword;
      futureNotices = apiService.fetchNotices(
          keyword: _keyword, excludeClosed: _excludeClosed);
    });
    _saveFilter(keyword: _keyword);
  }

  @override
  Widget build(BuildContext context) {
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
                // Change prefixIcon to IconButton
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
                        setState(() {
                          _excludeClosed = !_excludeClosed;
                          futureNotices = apiService.fetchNotices(
                              keyword: _keyword, excludeClosed: _excludeClosed);
                        });
                        _saveFilter(excludeClosed: _excludeClosed);
                      },
                      child: Row(
                        children: [
                          Checkbox(
                            value: _excludeClosed,
                            onChanged: (val) {
                              setState(() {
                                _excludeClosed = val ?? false;
                                futureNotices = apiService.fetchNotices(
                                    keyword: _keyword,
                                    excludeClosed: _excludeClosed);
                              });
                              _saveFilter(excludeClosed: _excludeClosed);
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
                            _triggerSearch(); // Trigger search with empty (reset)
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
              onPressed: _refreshNotices,
            ),
            IconButton(
              icon: const Icon(Icons.notifications_outlined),
              onPressed: () {},
            ),
            IconButton(
              icon: const Icon(Icons.person),
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
            _buildNoticeList(futureNotices),
            // Tab 2: Favorites
            _buildNoticeList(futureFavorites, isFavoriteTab: true),
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
    // Basic values (Backend should ideally provide this, but calculation requires it here for slider)
    // Construction: 87.745%
    // Service: 87.995%
    // Goods: 88.0%
    switch (widget.notice.contractType) {
      case 'SERVICE':
        return 87.995;
      case 'GOODS':
        return 88.0;
      case 'CONSTRUCTION':
      default:
        return 87.745;
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
                        // Submit logic
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
