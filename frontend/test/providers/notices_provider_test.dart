import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mocktail/mocktail.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:bideasy_app/providers/notices_provider.dart';
import '../helpers/mock_api_service.dart';
import '../helpers/provider_test_helper.dart';
import '../helpers/test_factories.dart';

void main() {
  late MockApiService mockApi;
  late ProviderContainer container;

  setUp(() {
    // Mock SharedPreferences for _saveFilter() calls
    SharedPreferences.setMockInitialValues({});
    mockApi = MockApiService();
    container = createTestContainer(mockApi);
  });

  tearDown(() {
    container.dispose();
  });

  group('NoticesState', () {
    test('default state has empty notices and no loading', () {
      final state = container.read(noticesProvider);
      expect(state.notices, isEmpty);
      expect(state.favorites, isEmpty);
      expect(state.isLoading, isFalse);
      expect(state.isLoadingMore, isFalse);
      expect(state.currentPage, 1);
      expect(state.keyword, isNull);
      expect(state.excludeClosed, isFalse);
      expect(state.favoriteIds, isEmpty);
      expect(state.competitionCache, isEmpty);
    });
  });

  group('NoticesNotifier', () {
    test('fetchNotices populates notices list on success', () async {
      final testNotices = [
        createTestNotice(bidNo: '001', title: '공사 A'),
        createTestNotice(bidNo: '002', title: '공사 B'),
      ];

      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenAnswer((_) async => testNotices);

      await container.read(noticesProvider.notifier).fetchNotices(isInitial: true);

      final state = container.read(noticesProvider);
      expect(state.notices.length, 2);
      expect(state.notices[0].title, '공사 A');
      expect(state.notices[1].title, '공사 B');
      expect(state.isLoading, isFalse);
    });

    test('fetchNotices sets isLoading false on error', () async {
      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenThrow(Exception('Network error'));

      await container.read(noticesProvider.notifier).fetchNotices(isInitial: true);

      final state = container.read(noticesProvider);
      expect(state.notices, isEmpty);
      expect(state.isLoading, isFalse);
    });

    test('loadMore increments page and appends notices', () async {
      final page1 = [createTestNotice(bidNo: '001')];
      final page2 = [createTestNotice(bidNo: '002')];

      var callCount = 0;
      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenAnswer((_) async {
        callCount++;
        return callCount == 1 ? page1 : page2;
      });

      // Initial load
      await container.read(noticesProvider.notifier).fetchNotices(isInitial: true);
      expect(container.read(noticesProvider).notices.length, 1);
      expect(container.read(noticesProvider).currentPage, 1);

      // Load more
      await container.read(noticesProvider.notifier).loadMore();
      expect(container.read(noticesProvider).notices.length, 2);
      expect(container.read(noticesProvider).currentPage, 2);
    });

    test('search resets notices and sets keyword', () async {
      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenAnswer((_) async => [createTestNotice(title: '도로 공사')]);

      await container.read(noticesProvider.notifier).search('도로');

      final state = container.read(noticesProvider);
      expect(state.keyword, '도로');
      expect(state.currentPage, 1);
      expect(state.notices.length, 1);
    });

    test('search with empty string sets keyword to null', () async {
      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenAnswer((_) async => []);

      await container.read(noticesProvider.notifier).search('');

      final state = container.read(noticesProvider);
      expect(state.keyword, isNull);
    });

    test('toggleFavorite adds and removes from favoriteIds', () async {
      when(() => mockApi.toggleFavorite(any())).thenAnswer((_) async {});
      when(() => mockApi.fetchFavorites()).thenAnswer((_) async => []);

      // Add favorite
      await container.read(noticesProvider.notifier).toggleFavorite('BID-001');
      expect(container.read(noticesProvider).favoriteIds, contains('BID-001'));

      // Remove favorite
      await container.read(noticesProvider.notifier).toggleFavorite('BID-001');
      expect(container.read(noticesProvider).favoriteIds, isNot(contains('BID-001')));
    });

    test('toggleExcludeClosed flips the filter and resets list', () async {
      when(() => mockApi.fetchNotices(
            keyword: any(named: 'keyword'),
            excludeClosed: any(named: 'excludeClosed'),
            page: any(named: 'page'),
          )).thenAnswer((_) async => []);

      expect(container.read(noticesProvider).excludeClosed, isFalse);

      await container.read(noticesProvider.notifier).toggleExcludeClosed();

      final state = container.read(noticesProvider);
      expect(state.excludeClosed, isTrue);
      expect(state.currentPage, 1);
    });

    test('fetchFavorites populates favorites list and ids', () async {
      final favs = [
        createTestNotice(bidNo: 'FAV-01', title: '즐겨찾기 공사'),
        createTestNotice(bidNo: 'FAV-02', title: '즐겨찾기 용역'),
      ];
      when(() => mockApi.fetchFavorites()).thenAnswer((_) async => favs);

      await container.read(noticesProvider.notifier).fetchFavorites();

      final state = container.read(noticesProvider);
      expect(state.favorites.length, 2);
      expect(state.favoriteIds, {'FAV-01', 'FAV-02'});
    });
  });
}
