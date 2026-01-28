import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:bideasy_app/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('E2E: Search Filter and Opening Results', (tester) async {
    // 1. Launch App
    app.main();
    await tester.pumpAndSettle();

    // 2. Verify Home Screen (search hint text exists)
    expect(find.text('공고명, 키워드 검색'), findsOneWidget);

    // 3. Test Filter Toggle
    // The checkbox is in the search bar
    final checkboxFinder = find.byType(Checkbox);
    expect(checkboxFinder, findsOneWidget);

    // Tap to toggle "Exclude Closed"
    await tester.tap(checkboxFinder);
    await tester.pumpAndSettle(const Duration(seconds: 2)); // Wait for API

    // Verify it doesn't crash and maybe refreshes
    // We can't easily verify exact data count without mocking, but app should remain stable.

    // Tap back to include closed (if we want to find closed bids)
    // Actually, "Exclude Closed" = Unchecked by default?
    // Code: bool _excludeClosed = false;
    // Tapping it makes it true (Exclude closed).
    // We want to FIND closed bids, so we should UNCHECK it (or leave it unchecked).
    // Let's toggle it back.
    await tester.tap(checkboxFinder);
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // 4. Test Search
    final searchField = find.byType(TextField);
    await tester.enterText(searchField, '공사'); // Generic term
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // 5. Check for Closed Bids (UI: "개찰 완료")
    final closedBadgeFinder = find.text('개찰 완료');
    if (closedBadgeFinder.evaluate().isNotEmpty) {
      print('Found ${closedBadgeFinder.evaluate().length} closed bids.');

      // Tap the first one (NoticeCard)
      // We tap the text, hit test should find the Card's InkWell.
      await tester.tap(closedBadgeFinder.first);
      await tester.pumpAndSettle();

      // 6. Verify Result Table Logic
      // Should show "개찰 순위" instead of Calculator.
      expect(find.text('개찰 순위'), findsOneWidget);
      expect(find.text('투찰금액'), findsOneWidget);

      // Close the sheet
      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
    } else {
      print('No closed bids "개찰 완료" found. Skipping Opening Result test.');
    }
  });
}
