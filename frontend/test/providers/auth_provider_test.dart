import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/providers/auth_provider.dart';

void main() {
  group('AuthState', () {
    test('default state has checking status', () {
      const state = AuthState();
      expect(state.status, AuthStatus.checking);
      expect(state.paymentResult, isNull);
      expect(state.paymentAmount, isNull);
      expect(state.paymentMessage, isNull);
    });

    test('copyWith preserves fields when not overridden', () {
      const state = AuthState(
        status: AuthStatus.authenticated,
        paymentResult: 'success',
        paymentAmount: '5000',
      );

      final copied = state.copyWith();
      expect(copied.status, AuthStatus.authenticated);
      expect(copied.paymentResult, 'success');
      expect(copied.paymentAmount, '5000');
    });

    test('copyWith clearPayment resets payment fields', () {
      const state = AuthState(
        status: AuthStatus.authenticated,
        paymentResult: 'success',
        paymentAmount: '5000',
        paymentMessage: 'done',
      );

      final cleared = state.copyWith(clearPayment: true);
      expect(cleared.status, AuthStatus.authenticated);
      expect(cleared.paymentResult, isNull);
      expect(cleared.paymentAmount, isNull);
      expect(cleared.paymentMessage, isNull);
    });
  });

  group('AuthNotifier', () {
    test('initial state is checking', () {
      final notifier = AuthNotifier();
      expect(notifier.state.status, AuthStatus.checking);
    });

    test('clearPayment resets payment fields', () {
      final notifier = AuthNotifier();
      // Simulate a state with payment info
      notifier.state = const AuthState(
        status: AuthStatus.authenticated,
        paymentResult: 'success',
        paymentAmount: '10000',
        paymentMessage: 'OK',
      );

      notifier.clearPayment();

      expect(notifier.state.status, AuthStatus.authenticated);
      expect(notifier.state.paymentResult, isNull);
      expect(notifier.state.paymentAmount, isNull);
      expect(notifier.state.paymentMessage, isNull);
    });
  });
}
