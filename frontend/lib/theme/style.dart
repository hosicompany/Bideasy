import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class AppColors {
  static const Color primaryBlue = Color(0xFF3182F6);
  static const Color backgroundGrey = Color(0xFFF2F4F6);
  static const Color surfaceWhite = Color(0xFFFFFFFF);
  
  static const Color textMain = Color(0xFF191F28);
  static const Color textSub = Color(0xFF8B95A1);
  
  static const Color safeGreen = Color(0xFF34C759);
  static const Color dangerRed = Color(0xFFFF3B30);
  
  static const Color divider = Color(0xFFE5E8EB);

  // Competition level colors
  static const Color competitionBlue = Color(0xFF3182F6);
  static const Color competitionGreen = Color(0xFF34C759);
  static const Color competitionYellow = Color(0xFFFFCC00);
  static const Color competitionOrange = Color(0xFFFF9500);
  static const Color competitionRed = Color(0xFFFF3B30);
}

class AppTextStyles {
  static const TextStyle h1 = TextStyle(
    fontSize: 26,
    fontWeight: FontWeight.w700,
    color: AppColors.textMain,
    fontFamily: 'Pretendard', 
  );
  
  static const TextStyle h2 = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w700,
    color: AppColors.textMain, // Slightly darker than sub
    fontFamily: 'Pretendard',
  );
  
  static const TextStyle body1 = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w500,
    color: Color(0xFF4E5968),
    fontFamily: 'Pretendard',
  );
  
  static const TextStyle caption = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    color: AppColors.textSub,
    fontFamily: 'Pretendard',
  );
}

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      scaffoldBackgroundColor: AppColors.backgroundGrey,
      primaryColor: AppColors.primaryBlue,
      fontFamily: 'Pretendard',
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.backgroundGrey,
        elevation: 0,
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        titleTextStyle: TextStyle(
          color: AppColors.textMain,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
        iconTheme: IconThemeData(color: AppColors.textMain),
      ),
      colorScheme: ColorScheme.fromSwatch().copyWith(
        secondary: AppColors.primaryBlue,
      ),
    );
  }
}
