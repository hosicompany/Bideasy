import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_service.dart';
import 'api_service_provider.dart';

class PointsState {
  final int balance;
  final List<Map<String, dynamic>> history;
  final bool isLoading;
  final String? error;

  const PointsState({
    this.balance = 0,
    this.history = const [],
    this.isLoading = true,
    this.error,
  });

  PointsState copyWith({
    int? balance,
    List<Map<String, dynamic>>? history,
    bool? isLoading,
    String? Function()? error,
  }) {
    return PointsState(
      balance: balance ?? this.balance,
      history: history ?? this.history,
      isLoading: isLoading ?? this.isLoading,
      error: error != null ? error() : this.error,
    );
  }
}

class PointsNotifier extends StateNotifier<PointsState> {
  final ApiService _api;

  PointsNotifier(this._api) : super(const PointsState());

  Future<void> loadData() async {
    state = state.copyWith(isLoading: true, error: () => null);

    try {
      final results = await Future.wait([
        _api.getPointBalance(),
        _api.getPointHistory(limit: 50),
      ]);

      final balance = results[0] as Map<String, dynamic>;
      final history = results[1] as List<Map<String, dynamic>>;

      state = state.copyWith(
        balance: balance['points'] ?? 0,
        history: history,
        isLoading: false,
      );
    } catch (e) {
      state = state.copyWith(
        error: () => e.toString(),
        isLoading: false,
      );
    }
  }
}

final pointsProvider =
    StateNotifierProvider<PointsNotifier, PointsState>((ref) {
  return PointsNotifier(ref.read(apiServiceProvider));
});
