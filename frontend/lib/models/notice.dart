import 'package:intl/intl.dart';

class Notice {
  // Core fields
  final String bidNo;
  final String title;
  final String content; // Notice URL
  final double basicPrice;
  final DateTime? startDate;
  final DateTime? endDate;
  final String? contractType;
  final String? organization;

  // Extended fields for AI analysis
  final String? demandOrganization;
  final String? bidMethod;
  final String? contractMethod;
  final String? bidType;
  final String? status;
  final String? region;
  final double? budgetAmount;
  final DateTime? openingDate;
  final String? internationalBid;
  final String? jointContract;
  final String? bigCompanyOk;
  final String? smeOnly;
  final String? bidQualification;
  final String? emergencyBid;
  final String? rebidYn;
  final String? attachmentUrl;
  final String? attachmentName;

  // Calculated fields (populated by AI Analysis or Calculator)
  final int? aValue;
  final int? netCost;

  Notice({
    required this.bidNo,
    required this.title,
    required this.content,
    required this.basicPrice,
    this.startDate,
    this.endDate,
    this.contractType,
    this.organization,
    this.demandOrganization,
    this.bidMethod,
    this.contractMethod,
    this.bidType,
    this.status,
    this.region,
    this.budgetAmount,
    this.openingDate,
    this.internationalBid,
    this.jointContract,
    this.bigCompanyOk,
    this.smeOnly,
    this.bidQualification,
    this.emergencyBid,
    this.rebidYn,
    this.attachmentUrl,
    this.attachmentName,
    this.aValue,
    this.netCost,
  });

  bool get isClosed {
    if (openingDate == null) return false;
    return DateTime.now().isAfter(openingDate!);
  }

  // Factory for JSON parsing with extended fields
  factory Notice.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(String? dateStr) {
      if (dateStr == null || dateStr.isEmpty) return null;
      try {
        // Handle "YYYY-MM-DD HH:mm:ss" typical in DB
        return DateTime.parse(dateStr.replaceAll(' ', 'T'));
      } catch (e) {
        return null;
      }
    }

    return Notice(
      // Core fields
      bidNo: json['bid_no'] ?? '',
      title: json['title'] ?? '',
      basicPrice: (json['basic_price'] ?? 0).toDouble(),
      contractType: json['contract_type'],
      content: json['content'] ?? '',
      startDate: parseDate(json['start_date']),
      endDate: parseDate(json['end_date']),
      organization: json['organization'],

      // Extended fields
      demandOrganization: json['demand_organization'],
      bidMethod: json['bid_method'],
      contractMethod: json['contract_method'],
      bidType: json['bid_type'],
      status: json['status'],
      region: json['region'],
      budgetAmount: json['budget_amount'] != null
          ? (json['budget_amount']).toDouble()
          : null,
      openingDate: parseDate(json['opening_date']),
      internationalBid: json['international_bid'],
      jointContract: json['joint_contract'],
      bigCompanyOk: json['big_company_ok'],
      smeOnly: json['sme_only'],
      bidQualification: json['bid_qualification'],
      emergencyBid: json['emergency_bid'],
      rebidYn: json['rebid_yn'],
      attachmentUrl: json['attachment_url'],
      attachmentName: json['attachment_name'],
    );
  }

  // Formatting helper
  String get formattedPrice {
    final formatter = NumberFormat('#,###');
    return formatter.format(basicPrice.toInt());
  }

  // Convert to query params for AI API
  Map<String, String> toAnalysisParams() {
    final params = <String, String>{};
    if (title.isNotEmpty) params['title'] = title;
    if (basicPrice > 0) params['basic_price'] = basicPrice.toString();
    if (organization != null) params['organization'] = organization!;
    if (demandOrganization != null) {
      params['demand_organization'] = demandOrganization!;
    }
    if (bidMethod != null) params['bid_method'] = bidMethod!;
    if (contractMethod != null) params['contract_method'] = contractMethod!;
    if (bidType != null) params['bid_type'] = bidType!;
    if (status != null) params['status'] = status!;
    if (region != null) params['region'] = region!;
    if (budgetAmount != null) params['budget_amount'] = budgetAmount.toString();
    if (openingDate != null)
      params['opening_date'] = openingDate!.toIso8601String(); // Use ISO format
    if (internationalBid != null) {
      params['international_bid'] = internationalBid!;
    }
    if (jointContract != null) params['joint_contract'] = jointContract!;
    if (bigCompanyOk != null) params['big_company_ok'] = bigCompanyOk!;
    if (smeOnly != null) params['sme_only'] = smeOnly!;
    if (emergencyBid != null) params['emergency_bid'] = emergencyBid!;
    if (rebidYn != null) params['rebid_yn'] = rebidYn!;
    if (attachmentUrl != null) params['attachment_url'] = attachmentUrl!;
    if (attachmentName != null) params['attachment_name'] = attachmentName!;
    if (startDate != null) params['start_date'] = startDate!.toIso8601String();
    if (endDate != null) params['end_date'] = endDate!.toIso8601String();
    if (content.isNotEmpty) params['notice_url'] = content;
    return params;
  }

  Notice copyWith({
    String? bidNo,
    String? title,
    String? content,
    double? basicPrice,
    DateTime? startDate,
    DateTime? endDate,
    String? contractType,
    String? organization,
    String? demandOrganization,
    String? bidMethod,
    String? contractMethod,
    String? bidType,
    String? status,
    String? region,
    double? budgetAmount,
    DateTime? openingDate,
    String? internationalBid,
    String? jointContract,
    String? bigCompanyOk,
    String? smeOnly,
    String? bidQualification,
    String? emergencyBid,
    String? rebidYn,
    String? attachmentUrl,
    String? attachmentName,
    int? aValue,
    int? netCost,
  }) {
    return Notice(
      bidNo: bidNo ?? this.bidNo,
      title: title ?? this.title,
      content: content ?? this.content,
      basicPrice: basicPrice ?? this.basicPrice,
      startDate: startDate ?? this.startDate,
      endDate: endDate ?? this.endDate,
      contractType: contractType ?? this.contractType,
      organization: organization ?? this.organization,
      demandOrganization: demandOrganization ?? this.demandOrganization,
      bidMethod: bidMethod ?? this.bidMethod,
      contractMethod: contractMethod ?? this.contractMethod,
      bidType: bidType ?? this.bidType,
      status: status ?? this.status,
      region: region ?? this.region,
      budgetAmount: budgetAmount ?? this.budgetAmount,
      openingDate: openingDate ?? this.openingDate,
      internationalBid: internationalBid ?? this.internationalBid,
      jointContract: jointContract ?? this.jointContract,
      bigCompanyOk: bigCompanyOk ?? this.bigCompanyOk,
      smeOnly: smeOnly ?? this.smeOnly,
      bidQualification: bidQualification ?? this.bidQualification,
      emergencyBid: emergencyBid ?? this.emergencyBid,
      rebidYn: rebidYn ?? this.rebidYn,
      attachmentUrl: attachmentUrl ?? this.attachmentUrl,
      attachmentName: attachmentName ?? this.attachmentName,
      aValue: aValue ?? this.aValue,
      netCost: netCost ?? this.netCost,
    );
  }
}
