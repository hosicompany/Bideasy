import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_service.dart';
import '../utils/web_utils.dart';

enum AuthStatus { checking, authenticated, unauthenticated }

class AuthState {
  final AuthStatus status;
  final String? paymentResult;
  final String? paymentAmount;
  final String? paymentMessage;

  const AuthState({
    this.status = AuthStatus.checking,
    this.paymentResult,
    this.paymentAmount,
    this.paymentMessage,
  });

  AuthState copyWith({
    AuthStatus? status,
    String? paymentResult,
    String? paymentAmount,
    String? paymentMessage,
    bool clearPayment = false,
  }) {
    return AuthState(
      status: status ?? this.status,
      paymentResult: clearPayment ? null : (paymentResult ?? this.paymentResult),
      paymentAmount: clearPayment ? null : (paymentAmount ?? this.paymentAmount),
      paymentMessage: clearPayment ? null : (paymentMessage ?? this.paymentMessage),
    );
  }
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier() : super(const AuthState());

  Future<void> checkAuth() async {
    // Check payment redirect
    String? paymentResult;
    String? paymentAmount;
    String? paymentMessage;

    final pr = getPaymentResultFromUrl();
    if (pr != null) {
      paymentResult = pr;
      paymentAmount = getPaymentAmountFromUrl();
      paymentMessage = getPaymentMessageFromUrl();
      cleanUrl();
    }

    // Check OAuth redirect
    final tokenFromUrl = getTokenFromUrl();
    if (tokenFromUrl != null && tokenFromUrl.isNotEmpty) {
      await ApiService.saveTokenDirect(tokenFromUrl);
      cleanUrl();
      state = AuthState(
        status: AuthStatus.authenticated,
        paymentResult: paymentResult,
        paymentAmount: paymentAmount,
        paymentMessage: paymentMessage,
      );
      return;
    }

    // Check OAuth error
    final errorFromUrl = getErrorFromUrl();
    if (errorFromUrl != null) {
      cleanUrl();
    }

    // Normal flow: check saved token
    final hasToken = await ApiService.loadToken();
    state = AuthState(
      status: hasToken ? AuthStatus.authenticated : AuthStatus.unauthenticated,
      paymentResult: paymentResult,
      paymentAmount: paymentAmount,
      paymentMessage: paymentMessage,
    );
  }

  void clearPayment() {
    state = state.copyWith(clearPayment: true);
  }

  Future<void> login({required String email, required String password}) async {
    await ApiService.login(email: email, password: password);
    state = const AuthState(status: AuthStatus.authenticated);
  }

  Future<void> logout() async {
    await ApiService.clearToken();
    state = const AuthState(status: AuthStatus.unauthenticated);
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier();
});
