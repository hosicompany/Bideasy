import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mocktail/mocktail.dart';
import 'package:bideasy_app/providers/user_provider.dart';
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

  group('UserNotifier', () {
    test('initial state is AsyncValue.data(null)', () {
      final state = container.read(userProvider);
      expect(state, isA<AsyncData<dynamic>>());
      expect(state.value, isNull);
    });

    test('loadUser sets data on success', () async {
      final testUser = createTestUser();
      when(() => mockApi.getUserMe()).thenAnswer((_) async => testUser);

      await container.read(userProvider.notifier).loadUser();

      final state = container.read(userProvider);
      expect(state.value, isNotNull);
      expect(state.value!.email, 'test@example.com');
      expect(state.value!.companyName, '테스트건설');
      expect(state.value!.points, 5000);
    });

    test('loadUser sets error on failure', () async {
      when(() => mockApi.getUserMe()).thenThrow(Exception('Network error'));

      await container.read(userProvider.notifier).loadUser();

      final state = container.read(userProvider);
      expect(state, isA<AsyncError<dynamic>>());
    });

    test('updateUser updates state with new data', () async {
      final originalUser = createTestUser(companyName: '원래건설');
      final updatedUser = createTestUser(companyName: '변경건설');

      when(() => mockApi.getUserMe()).thenAnswer((_) async => originalUser);
      when(() => mockApi.updateUserMe(any())).thenAnswer((_) async => updatedUser);

      // Load initial user
      await container.read(userProvider.notifier).loadUser();
      expect(container.read(userProvider).value!.companyName, '원래건설');

      // Update user
      await container.read(userProvider.notifier).updateUser({'company_name': '변경건설'});
      expect(container.read(userProvider).value!.companyName, '변경건설');
    });

    test('clear resets state to null', () async {
      final testUser = createTestUser();
      when(() => mockApi.getUserMe()).thenAnswer((_) async => testUser);

      await container.read(userProvider.notifier).loadUser();
      expect(container.read(userProvider).value, isNotNull);

      container.read(userProvider.notifier).clear();
      expect(container.read(userProvider).value, isNull);
    });
  });
}
