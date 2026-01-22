// This is a basic Flutter widget test for BidEasy app.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:bideasy_app/main.dart';

void main() {
  testWidgets('BidEasy app smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const ProviderScope(child: BidEasyApp()));

    // Verify that app title is displayed
    expect(find.text('BidEasy'), findsOneWidget);
  });
}
