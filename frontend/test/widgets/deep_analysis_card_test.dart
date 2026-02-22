import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/deep_analysis_card.dart';

void main() {
  Widget buildCard({String bidNo = 'TEST001'}) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: DeepAnalysisCard(bidNo: bidNo),
        ),
      ),
    );
  }

  testWidgets('renders trigger button initially', (tester) async {
    await tester.pumpWidget(buildCard());

    expect(find.text('첨부파일 심층 분석'), findsOneWidget);
    expect(find.text('규격서/특수조건의 독소조항을 AI가 분석해요'), findsOneWidget);
    expect(find.byIcon(Icons.description_outlined), findsOneWidget);
    expect(find.byIcon(Icons.arrow_forward_ios_rounded), findsOneWidget);
  });

  testWidgets('does not expand before tap', (tester) async {
    await tester.pumpWidget(buildCard());

    // Should not show loading or analysis content
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('첨부파일을 분석하고 있어요'), findsNothing);
    expect(find.text('다시 시도'), findsNothing);
  });

  testWidgets('trigger button has correct icon container style',
      (tester) async {
    await tester.pumpWidget(buildCard());

    // Verify the card has the expected structure
    expect(find.byType(InkWell), findsOneWidget);
    expect(find.byIcon(Icons.description_outlined), findsOneWidget);
    expect(find.byIcon(Icons.arrow_forward_ios_rounded), findsOneWidget);
  });
}
