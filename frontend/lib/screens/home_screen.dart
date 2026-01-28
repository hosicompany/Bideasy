import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'my_page_screen.dart';
import '../theme/style.dart';
import '../widgets/notice_card.dart';
import '../widgets/bid_slider.dart';
import '../widgets/ai_analysis_card.dart';
import '../widgets/opening_result_table.dart';
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

  @override
  void initState() {
    super.initState();
    futureFavorites = Future.value([]);
    _loadFilters();
    // fetchNotices called in _loadFilters or below
    // futureNotices = apiService.fetchNotices(); // Moved to _loadFilters
    _fetchFavorites();
  }

  Future<void> _loadFilters() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _keyword = prefs.getString('keyword');
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("즐겨찾기 변경 실패")),
        );
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(
                  "업데이트 완료${_keyword != null ? ' (Filter: $_keyword)' : ''}")),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("Error: $e")));
      }
    }
  }

  Widget _buildNoticeList(Future<List<Notice>> futureList) {
    return FutureBuilder<List<Notice>>(
      future: futureList,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        } else if (snapshot.hasError) {
          return Center(child: Text("Error: ${snapshot.error}"));
        } else if (!snapshot.hasData || snapshot.data!.isEmpty) {
          return const Center(
              child: Text("공고가 없습니다.",
                  style: TextStyle(color: Colors.grey, fontSize: 16)));
        }

        final notices = snapshot.data!;
        return ListView.builder(
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
        );
      },
    );
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
              controller: TextEditingController(text: _keyword),
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: "공고명, 키워드 검색",
                hintStyle: TextStyle(color: Colors.grey[500], fontSize: 14),
                prefixIcon: const Icon(Icons.search, color: Colors.grey),
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
                    if (_keyword != null && _keyword!.isNotEmpty)
                      IconButton(
                        icon: const Icon(Icons.clear, size: 20),
                        onPressed: () {
                          setState(() {
                            _keyword = null;
                            futureNotices = apiService.fetchNotices(
                                excludeClosed: _excludeClosed);
                          });
                          _saveFilter(keyword: ""); // Clear keyword
                        },
                      ),
                  ],
                ),
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
              onSubmitted: (value) {
                final newKeyword = value.trim();
                setState(() {
                  _keyword = newKeyword.isEmpty ? null : newKeyword;
                  futureNotices = apiService.fetchNotices(
                      keyword: _keyword, excludeClosed: _excludeClosed);
                });
                _saveFilter(keyword: _keyword);
              },
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
            FutureBuilder<List<Notice>>(
              future: futureFavorites,
              builder: (context, snapshot) {
                // Reuse logic but maybe futureFavorites needs explicit refresh handling if empty
                if (snapshot.connectionState == ConnectionState.waiting &&
                    !snapshot.hasData) {
                  return const Center(child: CircularProgressIndicator());
                }
                // Just use the helper
                return _buildNoticeList(futureFavorites);
              },
            ),
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
