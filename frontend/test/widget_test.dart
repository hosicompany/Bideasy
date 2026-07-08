// This is a basic Flutter widget test for BidEasy app.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:bideasy_app/main.dart';
import 'package:bideasy_app/providers/auth_provider.dart';

/// checkAuth를 no-op으로 만들어 checking 상태를 유지하는 테스트용 노티파이어.
/// 실 구현은 SharedPreferences·URL 파싱 등 플러그인을 타 테스트 환경에서
/// 동작할 수 없고, initState가 스케줄한 Future가 pending timer로 남아 실패한다.
class _FakeAuthNotifier extends AuthNotifier {
  @override
  Future<void> checkAuth() async {}
}

void main() {
  testWidgets('BidEasy app smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authProvider.overrideWith((ref) => _FakeAuthNotifier()),
        ],
        child: const BidEasyApp(),
      ),
    );

    // AuthGate starts in checking state, showing a loading spinner
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    // initState가 스케줄한 Future(() => checkAuth()) 타이머를 비워
    // teardown의 pending-timer 오류를 방지한다 (checkAuth는 no-op).
    await tester.pump(const Duration(milliseconds: 100));
  });
}
