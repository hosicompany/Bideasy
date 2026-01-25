import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:bideasy_app/main.dart' as app;
import 'package:bideasy_app/widgets/notice_card.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('E2E: App loads feed and opens calculator', (tester) async {
    // 1. Launch App
    app.main();
    await tester.pumpAndSettle();

    // 2. Verify Title
    expect(find.text('BidEasy'), findsOneWidget);

    // 3. Wait for data load (Skeleton or CircularProgress might be present first)
    // We'll wait a bit for the real API call to finish and UI to update.
    // In a real test, pumping for a specific condition is better, but pumpAndSettle often works for simple flows.
    await tester.pumpAndSettle(const Duration(seconds: 4));

    // 4. Verify Notice List is populated
    // We look for at least one NoticeCard.
    final noticeCardFinder = find.byType(NoticeCard);
    expect(noticeCardFinder, findsAtLeastNWidgets(1));

    // 5. Tap the first notice
    await tester.tap(noticeCardFinder.first);
    await tester.pumpAndSettle();

    // 6. Verify Calculator Sheet appears
    // We check for "기초금액" text which is in the CalculatorView
    expect(find.text('기초금액'), findsOneWidget);

    // 7. Verify "이 가격으로 저장하기" button exists
    expect(find.text('이 가격으로 저장하기'), findsOneWidget);

    // 8. Verify Slider Interaction (Drag to Dangerous Zone)
    // Slider min: -15.0. Lower limit is around -12.25%.
    // Dragging deeply left should trigger danger.
    final sliderFinder = find.byType(Slider);
    await tester.drag(sliderFinder, const Offset(-300, 0)); // Drag more to left
    await tester.pumpAndSettle();

    // Expect Danger Text
    expect(find.text('너무 낮은 가격이에요! (위험)'), findsOneWidget);

    // 9. Verify A I Analysis loads
    // Wait for API response (FutureBuilder)
    await tester.pumpAndSettle(const Duration(seconds: 5));
    expect(find.text('AI 공고 분석'), findsOneWidget);
  });
}
