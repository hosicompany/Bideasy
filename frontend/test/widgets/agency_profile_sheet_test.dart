import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bideasy_app/widgets/agency_profile_sheet.dart';

void main() {
  testWidgets('renders search bar with initial organization', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AgencyProfileSheet(initialOrganization: '강남구청'),
        ),
      ),
    );

    // Search field should contain the initial organization
    final textField = find.byType(TextField);
    expect(textField, findsOneWidget);

    final textFieldWidget = tester.widget<TextField>(textField);
    expect(textFieldWidget.controller?.text, '강남구청');
  });

  testWidgets('renders handle bar and search hint', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AgencyProfileSheet(initialOrganization: '서울시청'),
        ),
      ),
    );

    // Should have search icon
    expect(find.byIcon(Icons.search_rounded), findsOneWidget);
  });

  testWidgets('shows login required when not logged in', (tester) async {
    // ApiService.isLoggedIn is false by default in test environment
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AgencyProfileSheet(initialOrganization: '테스트기관'),
        ),
      ),
    );

    // Wait for the state to settle
    await tester.pump();

    expect(find.text('로그인 후 이용할 수 있어요'), findsOneWidget);
  });
}
