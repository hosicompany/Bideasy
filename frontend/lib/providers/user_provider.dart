import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user.dart';
import '../services/api_service.dart';
import 'api_service_provider.dart';

class UserNotifier extends StateNotifier<AsyncValue<User?>> {
  final ApiService _api;

  UserNotifier(this._api) : super(const AsyncValue.data(null));

  Future<void> loadUser() async {
    state = const AsyncValue.loading();
    try {
      final user = await _api.getUserMe();
      state = AsyncValue.data(user);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  Future<void> updateUser(Map<String, dynamic> data) async {
    try {
      final updated = await _api.updateUserMe(data);
      state = AsyncValue.data(updated);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  void clear() {
    state = const AsyncValue.data(null);
  }
}

final userProvider =
    StateNotifierProvider<UserNotifier, AsyncValue<User?>>((ref) {
  return UserNotifier(ref.read(apiServiceProvider));
});
