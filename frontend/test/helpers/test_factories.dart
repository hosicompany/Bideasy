import 'package:bideasy_app/models/notice.dart';
import 'package:bideasy_app/models/user.dart';

/// Create a test Notice with sensible defaults.
Notice createTestNotice({
  String bidNo = '20260223-001',
  String title = '서울시 도로 보수 공사',
  double basicPrice = 100000000,
  String content = 'https://example.com/notice',
  String? contractType = 'CONSTRUCTION',
  String? organization = '서울특별시',
  String? bidType = '공사',
  DateTime? openingDate,
  String? status,
}) {
  return Notice(
    bidNo: bidNo,
    title: title,
    basicPrice: basicPrice,
    content: content,
    contractType: contractType,
    organization: organization,
    bidType: bidType,
    openingDate: openingDate,
    status: status,
  );
}

/// Create a closed (past opening date) notice.
Notice createClosedNotice({
  String bidNo = '20260220-099',
  String title = '부산시 건축 공사 (개찰 완료)',
  double basicPrice = 50000000,
}) {
  return createTestNotice(
    bidNo: bidNo,
    title: title,
    basicPrice: basicPrice,
    openingDate: DateTime.now().subtract(const Duration(days: 1)),
  );
}

/// Create a test User with sensible defaults.
User createTestUser({
  int id = 1,
  String? email = 'test@example.com',
  String? companyName = '테스트건설',
  String? ceoName = '홍길동',
  String? licenses = '건축공사업',
  String? location = '서울특별시',
  int? capacityCost = 500000000,
  int? performanceRecord = 3,
  int points = 5000,
}) {
  return User(
    id: id,
    email: email,
    companyName: companyName,
    ceoName: ceoName,
    licenses: licenses,
    location: location,
    capacityCost: capacityCost,
    performanceRecord: performanceRecord,
    points: points,
  );
}

/// Create a test point transaction history item.
Map<String, dynamic> createTestPointTx({
  int amount = -500,
  String txType = 'BID_COPY',
  String? description = '투찰금액 복사',
  DateTime? createdAt,
}) {
  return {
    'amount': amount,
    'tx_type': txType,
    'description': description,
    'created_at': (createdAt ?? DateTime.now()).toIso8601String(),
  };
}
