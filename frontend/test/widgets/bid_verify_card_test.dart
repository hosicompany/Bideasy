import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/bid_verify_card.dart';
import 'package:bideasy_app/models/notice.dart';

void main() {
  final testNotice = Notice(
    bidNo: '20250101001',
    title: '테스트 공사',
    content: 'https://example.com',
    basicPrice: 100000000,
    organization: '서울시청',
  );

  Widget buildCard() {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: BidVerifyCard(notice: testNotice),
        ),
      ),
    );
  }

  testWidgets('renders header and badge', (tester) async {
    await tester.pumpWidget(buildCard());
    expect(find.text('내 투찰 결과 분석'), findsOneWidget);
    expect(find.text('역검증'), findsOneWidget);
  });

  testWidgets('renders input hint and button', (tester) async {
    await tester.pumpWidget(buildCard());
    expect(find.text('투찰가 입력'), findsOneWidget);
    expect(find.text('분석'), findsOneWidget);
  });

  testWidgets('renders prompt text', (tester) async {
    await tester.pumpWidget(buildCard());
    expect(
      find.text('내 투찰가를 입력하면 결과를 분석해드려요'),
      findsOneWidget,
    );
  });

  testWidgets('input formats digits with commas', (tester) async {
    await tester.pumpWidget(buildCard());
    final textField = find.byType(TextField);
    await tester.enterText(textField, '12345678');
    await tester.pump();
    expect(find.text('12,345,678'), findsOneWidget);
  });
}
