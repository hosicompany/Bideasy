import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:bideasy_app/providers/api_service_provider.dart';
import 'mock_api_service.dart';

/// Create a ProviderContainer with MockApiService override for testing.
ProviderContainer createTestContainer(MockApiService mockApi) {
  return ProviderContainer(
    overrides: [
      apiServiceProvider.overrideWithValue(mockApi),
    ],
  );
}
