import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/notice.dart';
import '../models/smart_bid.dart';
import '../services/api_service.dart';
import 'api_service_provider.dart';

class NoticesState {
  final List<Notice> notices;
  final List<Notice> favorites;
  final bool isLoading;
  final bool isLoadingMore;
  final int currentPage;
  final String? keyword;
  final bool excludeClosed;
  final Set<String> favoriteIds;
  final Map<String, CompetitionLevel> competitionCache;

  const NoticesState({
    this.notices = const [],
    this.favorites = const [],
    this.isLoading = false,
    this.isLoadingMore = false,
    this.currentPage = 1,
    this.keyword,
    this.excludeClosed = false,
    this.favoriteIds = const {},
    this.competitionCache = const {},
  });

  NoticesState copyWith({
    List<Notice>? notices,
    List<Notice>? favorites,
    bool? isLoading,
    bool? isLoadingMore,
    int? currentPage,
    String? Function()? keyword,
    bool? excludeClosed,
    Set<String>? favoriteIds,
    Map<String, CompetitionLevel>? competitionCache,
  }) {
    return NoticesState(
      notices: notices ?? this.notices,
      favorites: favorites ?? this.favorites,
      isLoading: isLoading ?? this.isLoading,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      currentPage: currentPage ?? this.currentPage,
      keyword: keyword != null ? keyword() : this.keyword,
      excludeClosed: excludeClosed ?? this.excludeClosed,
      favoriteIds: favoriteIds ?? this.favoriteIds,
      competitionCache: competitionCache ?? this.competitionCache,
    );
  }
}

class NoticesNotifier extends StateNotifier<NoticesState> {
  final ApiService _api;

  NoticesNotifier(this._api) : super(const NoticesState());

  /// Load saved filters from SharedPreferences, then fetch initial data
  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    final keyword = prefs.getString('keyword');
    final excludeClosed = prefs.getBool('exclude_closed') ?? false;

    state = state.copyWith(
      keyword: () => keyword,
      excludeClosed: excludeClosed,
      currentPage: 1,
      notices: [],
    );

    await Future.wait([
      fetchNotices(isInitial: true),
      fetchFavorites(),
    ]);
  }

  Future<void> fetchNotices({bool isInitial = false}) async {
    if (isInitial) {
      state = state.copyWith(isLoading: true);
    }

    try {
      final newNotices = await _api.fetchNotices(
        keyword: state.keyword,
        excludeClosed: state.excludeClosed,
        page: state.currentPage,
      );

      if (isInitial) {
        state = state.copyWith(notices: newNotices, isLoading: false, isLoadingMore: false);
      } else {
        state = state.copyWith(
          notices: [...state.notices, ...newNotices],
          isLoading: false,
          isLoadingMore: false,
        );
      }

      // Background competition level loading
      fetchCompetitionLevels();
    } catch (_) {
      state = state.copyWith(isLoading: false, isLoadingMore: false);
    }
  }

  Future<void> loadMore() async {
    state = state.copyWith(
      isLoadingMore: true,
      currentPage: state.currentPage + 1,
    );
    await fetchNotices(isInitial: false);
  }

  Future<void> search(String? keyword) async {
    final k = (keyword == null || keyword.trim().isEmpty) ? null : keyword.trim();
    state = state.copyWith(
      keyword: () => k,
      currentPage: 1,
      notices: [],
    );
    await _saveFilter(keyword: k);
    await fetchNotices(isInitial: true);
  }

  Future<void> toggleExcludeClosed() async {
    state = state.copyWith(
      excludeClosed: !state.excludeClosed,
      currentPage: 1,
      notices: [],
    );
    await _saveFilter(excludeClosed: state.excludeClosed);
    await fetchNotices(isInitial: true);
  }

  Future<void> refreshNotices() async {
    await _api.triggerCrawl();
    await fetchFavorites();

    state = state.copyWith(currentPage: 1, notices: []);
    await fetchNotices(isInitial: true);
  }

  Future<void> fetchFavorites() async {
    try {
      final favorites = await _api.fetchFavorites();
      state = state.copyWith(
        favorites: favorites,
        favoriteIds: favorites.map((n) => n.bidNo).toSet(),
      );
    } catch (_) {
      state = state.copyWith(favorites: []);
    }
  }

  Future<void> toggleFavorite(String bidNo) async {
    // Optimistic update
    final newIds = Set<String>.from(state.favoriteIds);
    if (newIds.contains(bidNo)) {
      newIds.remove(bidNo);
    } else {
      newIds.add(bidNo);
    }
    state = state.copyWith(favoriteIds: newIds);

    try {
      await _api.toggleFavorite(bidNo);
      // Refresh favorites list in background
      fetchFavorites();
    } catch (_) {
      // Revert on failure
      final revertIds = Set<String>.from(state.favoriteIds);
      if (revertIds.contains(bidNo)) {
        revertIds.remove(bidNo);
      } else {
        revertIds.add(bidNo);
      }
      state = state.copyWith(favoriteIds: revertIds);
      rethrow; // Let UI handle the error
    }
  }

  /// Background competition level fetching (progressive enhancement)
  Future<void> fetchCompetitionLevels() async {
    final uncached = state.notices
        .where((n) => !n.isClosed && !state.competitionCache.containsKey(n.bidNo))
        .toList();
    if (uncached.isEmpty) return;

    for (final notice in uncached) {
      try {
        final prediction = await _api.predictCompetition(
          bidType: normalizeBidType(notice.bidType),
          estimatedAmount: notice.basicPrice,
          agencyName: notice.organization ?? '',
        );
        final updated = Map<String, CompetitionLevel>.from(state.competitionCache);
        updated[notice.bidNo] = CompetitionLevel.fromBucket(prediction.predictedBucket);
        state = state.copyWith(competitionCache: updated);
      } catch (_) {
        // Silently skip — badge just won't show
      }
    }
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
}

final noticesProvider =
    StateNotifierProvider<NoticesNotifier, NoticesState>((ref) {
  return NoticesNotifier(ref.read(apiServiceProvider));
});
