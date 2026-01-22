import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'theme/style.dart';
import 'screens/home_screen.dart';

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
    );
  }
}
