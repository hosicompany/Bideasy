import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'theme/style.dart';
import 'screens/home_screen.dart';
import 'screens/bid_calculator_screen.dart';
import 'models/notice.dart';

void main() {
  runApp(const ProviderScope(child: BidEasyApp()));
}

class BidEasyApp extends StatelessWidget {
  const BidEasyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BidEasy',
      theme: AppTheme.lightTheme,
      home: const HomeScreen(),
      debugShowCheckedModeBanner: false,
      onGenerateRoute: (settings) {
        if (settings.name == '/calculator') {
          final notice = settings.arguments as Notice;
          return MaterialPageRoute(
            builder: (context) => BidCalculatorScreen(notice: notice),
          );
        }
        return null;
      },
    );
  }
}
