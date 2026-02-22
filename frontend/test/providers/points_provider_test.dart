import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mocktail/mocktail.dart';
import 'package:bideasy_app/providers/points_provider.dart';
import '../helpers/mock_api_service.dart';
import '../helpers/provider_test_helper.dart';
import '../helpers/test_factories.dart';

void main() {
  late MockApiService mockApi;
  late ProviderContainer container;

  setUp(() {
    mockApi = MockApiService();
    container = createTestContainer(mockApi);
  });

  tearDown(() {
    container.dispose();
  });

  group('PointsState', () {
    test('default state has zero balance and loading true', () {
      final state = container.read(pointsProvider);
      expect(state.balance, 0);
      expect(state.history, isEmpty);
      expect(state.isLoading, isTrue);
      expect(state.error, isNull);
    });
  });

  group('PointsNotifier', () {
    test('loadData sets balance and history on success', () async {
      final history = [
        createTestPointTx(amount: 5000, txType: 'CHARGE', description: '포인트 충전'),
        createTestPointTx(amount: -500, txType: 'BID_COPY', description: '투찰금액 복사'),
      ];

      when(() => mockApi.getPointBalance())
          .thenAnswer((_) async => {'points': 4500});
      when(() => mockApi.getPointHistory(limit: any(named: 'limit')))
          .thenAnswer((_) async => history);

      await container.read(pointsProvider.notifier).loadData();

      final state = container.read(pointsProvider);
      expect(state.balance, 4500);
      expect(state.history.length, 2);
      expect(state.isLoading, isFalse);
      expect(state.error, isNull);
    });

    test('loadData sets error on failure', () async {
      when(() => mockApi.getPointBalance())
          .thenThrow(Exception('Server error'));
      when(() => mockApi.getPointHistory(limit: any(named: 'limit')))
          .thenThrow(Exception('Server error'));

      await container.read(pointsProvider.notifier).loadData();

      final state = container.read(pointsProvider);
      expect(state.error, isNotNull);
      expect(state.error, contains('Server error'));
      expect(state.isLoading, isFalse);
    });

    test('loadData resets error on retry success', () async {
      // First call: error
      when(() => mockApi.getPointBalance())
          .thenThrow(Exception('fail'));
      when(() => mockApi.getPointHistory(limit: any(named: 'limit')))
          .thenThrow(Exception('fail'));

      await container.read(pointsProvider.notifier).loadData();
      expect(container.read(pointsProvider).error, isNotNull);

      // Second call: success
      when(() => mockApi.getPointBalance())
          .thenAnswer((_) async => {'points': 1000});
      when(() => mockApi.getPointHistory(limit: any(named: 'limit')))
          .thenAnswer((_) async => <Map<String, dynamic>>[]);

      await container.read(pointsProvider.notifier).loadData();
      final state = container.read(pointsProvider);
      expect(state.error, isNull);
      expect(state.balance, 1000);
    });
  });
}
